"""Worker pool manager for parallel gremlin execution.

This module provides the WorkerPool class that manages a pool of worker processes
for running mutation tests in parallel.

Note: This module uses ProcessPoolExecutor which internally uses pickle for
inter-process communication. The data being serialized is entirely under our
control (WorkerResult dataclass with primitive types) - no untrusted external
content is ever deserialized.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import (
    Future,
    InvalidStateError,
    ProcessPoolExecutor,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import partial
import logging
import multiprocessing
import multiprocessing.queues
import os
from pathlib import Path
import subprocess
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Self,
)

from pytest_gremlins.instrumentation.spawn_hook import export_spawn_hook
from pytest_gremlins.parallel.exit_codes import (
    COLLECTION_KILLING_TEST,
    GREMLIN_COLLECTION_FAILED_EXIT_CODE,
)
from pytest_gremlins.parallel.lightweight import (
    build_lightweight_command,
    describe_runner_error,
)
from pytest_gremlins.parallel.worker_kill import kill_process_tree
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.xdist_options import env_without_xdist_addopts

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

DEADLINE_GRACE_SECONDS = 10.0
"""How long past its mutant timeout a gremlin may run before the parent kills its worker (#976).

The worker enforces the mutant timeout itself and normally returns within a moment of it. The margin covers
the kill and the pipe drain after that, so a healthy timeout is never overtaken by the watchdog.
"""

_start_reports: Any = None
"""In a worker: the queue on which it tells the parent which gremlin it started and its own pid."""


@dataclass(frozen=True)
class WorkerResult:
    """Result from a worker process.

    This is a simplified result that can be passed between processes.
    Unlike GremlinResult, it doesn't contain AST nodes which cannot be
    serialized for multiprocessing.

    Attributes:
        gremlin_id: The ID of the gremlin that was tested.
        status: The outcome of testing the gremlin.
        killing_test: Name of test that killed the gremlin (if any).
        execution_time_ms: Time taken to test this gremlin.
        error_output: Captured stderr or exception message when status is ERROR.
    """

    gremlin_id: str
    status: GremlinResultStatus
    killing_test: str | None = None
    execution_time_ms: float | None = None
    error_output: str = ''


def _init_worker(report_queue: multiprocessing.queues.SimpleQueue[tuple[str, int, float]]) -> None:  # pragma: no cover
    """Pool worker initializer: remember the queue the worker reports its starts on."""
    global _start_reports  # noqa: PLW0603
    _start_reports = report_queue


def _run_watched(  # pragma: no cover
    target: Callable[[str, list[str], str, dict[str, str], int], WorkerResult],
    arguments: tuple[str, list[str], str, dict[str, str], int],
) -> WorkerResult:
    """Tell the parent this gremlin started here, then run it; the parent times it from that report."""
    _start_reports.put((arguments[0], os.getpid(), time.monotonic()))
    return target(*arguments)


def _run_gremlin_test(  # pragma: no cover
    gremlin_id: str,
    test_command: list[str],
    rootdir: str,
    env_vars: dict[str, str],
    timeout: int,
) -> WorkerResult:
    """Execute tests for a single gremlin in a worker process.

    This function runs in a separate process and executes the test command
    with the ACTIVE_GREMLIN environment variable set.

    Args:
        gremlin_id: The ID of the gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory for test execution.
        env_vars: Additional environment variables to set.
        timeout: Timeout in seconds.

    Returns:
        WorkerResult with the outcome of testing.
    """
    start_time = time.monotonic()

    env = env_without_xdist_addopts({**os.environ, **env_vars})
    env['ACTIVE_GREMLIN'] = gremlin_id
    env['GREMLIN_ROOTDIR'] = rootdir
    export_spawn_hook(env)

    # Use lightweight runner if available (skips full pytest startup)
    lightweight_cmd = build_lightweight_command(test_command, env_vars)
    effective_command = lightweight_cmd if lightweight_cmd is not None else test_command

    try:
        result = subprocess.run(  # Intentional: runs pytest test commands
            effective_command,
            cwd=rootdir,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        execution_time_ms = (time.monotonic() - start_time) * 1000

        # Only return code 1 (tests failed) should be treated as a mutation
        # being zapped. Other non-zero return codes indicate pytest errors
        # (collection/import/internal) and should not inflate the score.
        if result.returncode == 0:
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.SURVIVED,
                execution_time_ms=execution_time_ms,
            )
        if result.returncode == 1:
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.ZAPPED,
                killing_test='unknown',
                execution_time_ms=execution_time_ms,
            )
        if result.returncode == GREMLIN_COLLECTION_FAILED_EXIT_CODE:
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.ZAPPED,
                killing_test=COLLECTION_KILLING_TEST,
                execution_time_ms=execution_time_ms,
            )
        error_output = describe_runner_error(result.returncode, result.stderr)
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.ERROR,
            execution_time_ms=execution_time_ms,
            error_output=error_output,
        )
    except subprocess.TimeoutExpired:
        execution_time_ms = (time.monotonic() - start_time) * 1000
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.TIMEOUT,
            execution_time_ms=execution_time_ms,
        )
    except Exception as exc:
        logger.warning('Error testing gremlin %s: %s', gremlin_id, exc)
        execution_time_ms = (time.monotonic() - start_time) * 1000
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.ERROR,
            execution_time_ms=execution_time_ms,
            error_output=str(exc)[:2000],
        )


@dataclass
class _Job:
    """One submitted gremlin: what to run again if its executor is replaced, and where it stands."""

    gremlin_id: str
    arguments: tuple[str, list[str], str, dict[str, str], int]
    outcome: Future[WorkerResult]
    generation: int = 0
    pid: int | None = None
    started_at: float | None = None

    def settle(self, result: WorkerResult | None = None, error: BaseException | None = None) -> None:
        """Resolve the future the caller holds, once; later attempts are ignored."""
        try:
            if error is not None:
                self.outcome.set_exception(error)
            else:
                self.outcome.set_result(result)  # type: ignore[arg-type]
        except InvalidStateError:
            return


class WorkerPool:
    """Manages a pool of worker processes for parallel mutation testing.

    The worker pool wraps a ProcessPoolExecutor and provides lifecycle management
    for parallel gremlin execution. Workers are isolated processes that each set
    their own ACTIVE_GREMLIN environment variable.

    A worker enforces the mutant timeout itself, but a worker that hangs outside that call would hold the run
    for ever (#976). Each worker reports when it starts a gremlin, and :meth:`service` (called by the loop that
    collects results) gives a gremlin that runs ``timeout + grace_seconds`` past its start a TIMEOUT verdict,
    kills the worker with everything it started, and replaces the executor. Gremlins that were queued or in
    flight on the other workers are run again on the new executor, so their verdicts are unaffected.

    Attributes:
        max_workers: Maximum number of worker processes.
        timeout: Timeout in seconds for individual gremlin tests.

    Example:
        >>> with WorkerPool(max_workers=4) as pool:
        ...     # Submit work to pool
        ...     pass
    """

    def __init__(
        self,
        max_workers: int | None = None,
        timeout: int = 30,
        grace_seconds: float = DEADLINE_GRACE_SECONDS,
        worker_target: Callable[[str, list[str], str, dict[str, str], int], WorkerResult] | None = None,
    ) -> None:
        """Initialize the worker pool.

        Args:
            max_workers: Maximum number of worker processes. Defaults to CPU count.
            timeout: Timeout in seconds for individual tests. Defaults to 30.
            grace_seconds: Time past ``timeout`` before a gremlin's worker is killed. Defaults to
                :data:`DEADLINE_GRACE_SECONDS`.
            worker_target: Function a worker runs for one gremlin; replaced only by tests.
        """
        self._max_workers = max_workers if max_workers is not None else (os.cpu_count() or 4)
        self._timeout = timeout
        self._grace_seconds = grace_seconds
        self._worker_target = worker_target if worker_target is not None else _run_gremlin_test
        self._executor: ProcessPoolExecutor | None = None
        self._reports: Any = None
        self._generation = 0
        self._breaking_generation = -1
        self._jobs: dict[str, _Job] = {}
        self._settled_ids: deque[str] = deque()
        self._shutdown_called = False

    @property
    def max_workers(self) -> int:
        """Return the maximum number of workers."""
        return self._max_workers

    @property
    def timeout(self) -> int:
        """Return the timeout in seconds."""
        return self._timeout

    def __enter__(self) -> Self:
        """Enter the context manager, starting the worker pool."""
        self._start_executor()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the context manager, shutting down the pool."""
        self.shutdown(wait=True)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the worker pool.

        Args:
            wait: If True, wait for pending work to complete. If False, cancel
                  pending work immediately.
        """
        if self._shutdown_called:
            return

        self._shutdown_called = True
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
            self._executor = None

    def submit(
        self,
        gremlin_id: str,
        test_command: list[str],
        rootdir: str,
        instrumented_dir: str | None,
        env_vars: dict[str, str],
    ) -> Future[WorkerResult]:
        """Submit a gremlin test for execution.

        Args:
            gremlin_id: The ID of the gremlin to test.
            test_command: Command to run tests.
            rootdir: Root directory for test execution.
            instrumented_dir: Directory with instrumented sources (or None).
            env_vars: Additional environment variables to set.

        Returns:
            Future that will contain the WorkerResult when complete.

        Raises:
            RuntimeError: If the pool is not active (not in context).
        """
        if self._executor is None:
            msg = 'WorkerPool is not active. Use as context manager.'
            raise RuntimeError(msg)

        # Add instrumented dir to env vars if provided
        all_env_vars = dict(env_vars)
        if instrumented_dir is not None:
            all_env_vars['PYTEST_GREMLINS_SOURCES_FILE'] = str(Path(instrumented_dir) / 'sources.json')

        # Suppress subprocess coverage tracking: sitecustomize.py fires at Python startup
        # before --no-cov takes effect, so we explicitly clear the env var here.
        all_env_vars['COVERAGE_PROCESS_START'] = ''

        job = _Job(
            gremlin_id=gremlin_id,
            arguments=(gremlin_id, test_command, rootdir, all_env_vars, self._timeout),
            outcome=Future(),
        )
        self._jobs[gremlin_id] = job
        job.outcome.add_done_callback(lambda _outcome: self._settled_ids.append(gremlin_id))
        self._dispatch(job)
        return job.outcome

    def service(self) -> list[str]:
        """Enforce the per-gremlin deadline; call it regularly from the thread that collects results.

        A gremlin is overdue ``timeout + grace_seconds`` after its worker reported starting it. Overdue
        gremlins get a TIMEOUT verdict, and the executor is replaced as described in the class docstring.

        Returns:
            The ids of the gremlins scored TIMEOUT by this call.
        """
        if self._executor is None:
            return []
        self._forget_settled_jobs()
        self._read_start_reports()
        now = time.monotonic()
        overdue = [job for job in self._unfinished_jobs() if self._is_overdue(job, now)]
        if not overdue:
            return []
        return [job.gremlin_id for job in self._replace_executor_after_hang(overdue, now)]

    def _start_executor(self) -> None:
        context = multiprocessing.get_context()
        self._reports = context.SimpleQueue()
        self._generation += 1
        self._executor = ProcessPoolExecutor(
            max_workers=self._max_workers,
            mp_context=context,
            initializer=_init_worker,
            initargs=(self._reports,),
        )

    def _dispatch(self, job: _Job) -> None:
        assert self._executor is not None  # noqa: S101
        job.generation = self._generation
        job.pid = None
        job.started_at = None
        inner = self._executor.submit(_run_watched, self._worker_target, job.arguments)
        inner.add_done_callback(partial(self._relay, job, job.generation))

    def _relay(self, job: _Job, generation: int, inner: Future[WorkerResult]) -> None:
        """Hand an executor future's outcome to the caller's future (runs on an executor thread)."""
        if generation != self._generation or inner.cancelled():
            return
        error = inner.exception()
        if error is None:
            job.settle(result=inner.result())
        elif isinstance(error, BrokenProcessPool) and generation == self._breaking_generation:
            return  # the watchdog broke this executor on purpose and is about to run the job again
        else:
            job.settle(error=error)

    def _read_start_reports(self) -> None:
        while not self._reports.empty():
            gremlin_id, pid, started_at = self._reports.get()
            job = self._jobs.get(gremlin_id)
            if job is not None and job.pid is None:
                job.pid, job.started_at = pid, started_at

    def _forget_settled_jobs(self) -> None:
        """Drop jobs whose future is settled, so each call scans only the gremlins still in flight."""
        while self._settled_ids:
            self._jobs.pop(self._settled_ids.popleft(), None)

    def _unfinished_jobs(self) -> list[_Job]:
        return [job for job in self._jobs.values() if not job.outcome.done()]

    def _is_overdue(self, job: _Job, now: float) -> bool:
        return job.started_at is not None and now - job.started_at > self._timeout + self._grace_seconds

    def _replace_executor_after_hang(self, overdue: list[_Job], now: float) -> list[_Job]:
        """Score the hung gremlins TIMEOUT, rebuild the executor, and return every gremlin scored.

        Also scored are the gremlins in flight on other workers that have already run for their whole mutant
        timeout: the timeout their own test run enforces has passed, so they would be scored TIMEOUT anyway, and
        a fresh start would give them a second full deadline. Only gremlins still within their timeout restart,
        so a healthy gremlin waits less than one timeout before the rebuild and at most one timeout plus the
        grace margin after it.
        """
        old_executor = self._executor
        assert old_executor is not None  # noqa: S101
        worker_pids = self._worker_pids(old_executor)
        past_their_timeout = [
            job
            for job in self._unfinished_jobs()
            if job not in overdue and job.started_at is not None and now - job.started_at >= self._timeout
        ]
        for job in overdue:
            logger.warning(
                'Gremlin %s ran %.0fs past its start, beyond the %ss mutant timeout plus %ss grace: '
                'its worker (pid %s) is hung. Recording TIMEOUT and killing the worker.',
                job.gremlin_id,
                now - (job.started_at or now),
                self._timeout,
                self._grace_seconds,
                job.pid,
            )
        for job in past_their_timeout:
            logger.warning(
                'Gremlin %s was in flight on a worker killed for another hang and had already run %.0fs, '
                'past the %ss mutant timeout. Recording TIMEOUT instead of restarting it.',
                job.gremlin_id,
                now - (job.started_at or now),
                self._timeout,
            )
        scored = [*overdue, *past_their_timeout]
        for job in scored:
            elapsed_ms = (now - (job.started_at or now)) * 1000
            job.settle(
                result=WorkerResult(
                    gremlin_id=job.gremlin_id, status=GremlinResultStatus.TIMEOUT, execution_time_ms=elapsed_ms
                )
            )
        self._breaking_generation = self._generation
        for worker_pid in worker_pids:
            kill_process_tree(worker_pid)
        old_executor.shutdown(wait=True, cancel_futures=True)
        self._start_executor()
        for job in self._unfinished_jobs():
            self._dispatch(job)
        return scored

    def _worker_pids(self, executor: ProcessPoolExecutor) -> set[int]:
        """Return the pids of every worker of ``executor``, including ones whose start report is not read yet."""
        worker_processes = getattr(executor, '_processes', None) or {}
        pids = {int(pid) for pid in worker_processes}
        return pids | {job.pid for job in self._unfinished_jobs() if job.pid is not None}
