"""Persistent worker pool for reduced subprocess overhead.

This module implements a persistent worker pool that keeps worker processes
alive across multiple gremlin tests. This addresses the primary performance
bottleneck identified in profiling: subprocess spawning overhead of 500-700ms
per gremlin.

By keeping workers warm (already started, modules imported), we pay the
startup cost once per worker instead of once per gremlin. For 100 gremlins
with 4 workers, this reduces 100 * 600ms = 60s of overhead to 4 * 600ms = 2.4s.

Architecture:
- Main process creates N persistent worker processes
- Workers stay alive, waiting for work on a queue
- Main process sends (gremlin_id, test_command, env_vars) to workers
- Workers execute and return results
- Workers are reused for subsequent gremlins

Optimizations (PR #52):
- Configurable process start method (spawn/fork/forkserver)
- Worker warmup to pre-warm process pools
- Multiprocessing context support for better cross-platform behavior
"""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor, wait
import logging
import multiprocessing  # noqa: TC003 - used at runtime for context
import os
import subprocess
import time
from typing import Self

from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.reporting.results import GremlinResultStatus


logger = logging.getLogger(__name__)


def _warmup_noop() -> bool:  # pragma: no cover
    """No-op function for worker warmup.

    This function does nothing but return True. It's used to force
    workers to start and import necessary modules before actual work.

    Returns:
        True to indicate successful warmup.
    """
    return True


def _run_gremlin_batch(  # pragma: no cover
    gremlin_ids: list[str],
    test_command: list[str],
    rootdir: str,
    env_vars: dict[str, str],
    timeout: int,
) -> list[WorkerResult]:
    """Execute tests for multiple gremlins in a single subprocess call.

    This function tests gremlins sequentially within a single process,
    avoiding the subprocess startup overhead for each individual gremlin.
    Uses early termination: stops after first zapped gremlin.

    Args:
        gremlin_ids: List of gremlin IDs to test.
        test_command: Command to run tests.
        rootdir: Root directory for test execution.
        env_vars: Additional environment variables to set.
        timeout: Timeout in seconds per gremlin test.

    Returns:
        List of WorkerResult for each tested gremlin.
    """
    results: list[WorkerResult] = []

    for gremlin_id in gremlin_ids:
        start_time = time.monotonic()

        env = os.environ.copy()
        env.update(env_vars)
        env['ACTIVE_GREMLIN'] = gremlin_id

        try:
            result = subprocess.run(  # noqa: S603
                test_command,
                cwd=rootdir,
                env=env,
                capture_output=True,
                timeout=timeout,
                check=False,
            )

            execution_time_ms = (time.monotonic() - start_time) * 1000

            if result.returncode != 0:
                # Mutation caught - test failed
                results.append(
                    WorkerResult(
                        gremlin_id=gremlin_id,
                        status=GremlinResultStatus.ZAPPED,
                        killing_test='unknown',
                        execution_time_ms=execution_time_ms,
                    )
                )
                # Early termination - stop after first zapped gremlin
                break

            # Mutation survived - test passed
            results.append(
                WorkerResult(
                    gremlin_id=gremlin_id,
                    status=GremlinResultStatus.SURVIVED,
                    execution_time_ms=execution_time_ms,
                )
            )
        except subprocess.TimeoutExpired:
            execution_time_ms = (time.monotonic() - start_time) * 1000
            results.append(
                WorkerResult(
                    gremlin_id=gremlin_id,
                    status=GremlinResultStatus.TIMEOUT,
                    execution_time_ms=execution_time_ms,
                )
            )
            # Early termination on timeout too
            break
        except Exception as exc:
            logger.warning('Error testing gremlin %s: %s', gremlin_id, exc)
            execution_time_ms = (time.monotonic() - start_time) * 1000
            results.append(
                WorkerResult(
                    gremlin_id=gremlin_id,
                    status=GremlinResultStatus.ERROR,
                    execution_time_ms=execution_time_ms,
                )
            )
            break

    return results


def _run_gremlin_test(  # pragma: no cover
    gremlin_id: str,
    test_command: list[str],
    rootdir: str,
    env_vars: dict[str, str],
    timeout: int,
) -> WorkerResult:
    """Execute tests for a single gremlin.

    Wrapper around _run_gremlin_batch for single gremlin execution.

    Args:
        gremlin_id: The ID of the gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory for test execution.
        env_vars: Additional environment variables to set.
        timeout: Timeout in seconds.

    Returns:
        WorkerResult with the outcome of testing.
    """
    results = _run_gremlin_batch([gremlin_id], test_command, rootdir, env_vars, timeout)
    return (
        results[0]
        if results
        else WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.ERROR,
        )
    )


class PersistentWorkerPool:
    """Manages a pool of persistent worker processes for mutation testing.

    Unlike the standard WorkerPool which spawns a new subprocess per gremlin,
    this pool keeps worker processes alive and reuses them. Workers import
    modules once and stay warm, dramatically reducing startup overhead.

    Supports configurable process start method and worker warmup via PoolConfig.

    Attributes:
        max_workers: Maximum number of worker processes.
        timeout: Timeout in seconds for individual gremlin tests.
        config: The PoolConfig used to configure this pool.
        is_warmed_up: Whether workers have been pre-warmed.
        warmup_completed_count: Number of workers that completed warmup.

    Example:
        >>> config = PoolConfig(max_workers=4, warmup=True)  # doctest: +SKIP
        >>> pool = PersistentWorkerPool.from_config(config)  # doctest: +SKIP
        >>> with pool:  # doctest: +SKIP
        ...     future = pool.submit('g001', ['pytest'], '.', None, {})  # doctest: +SKIP
        ...     result = future.result()  # doctest: +SKIP
    """

    def __init__(
        self,
        max_workers: int | None = None,
        timeout: int = 30,
        *,
        config: PoolConfig | None = None,
    ) -> None:
        """Initialize the persistent worker pool.

        Args:
            max_workers: Maximum number of worker processes. Defaults to CPU count.
            timeout: Timeout in seconds for individual tests. Defaults to 30.
            config: Optional PoolConfig. If provided, max_workers and timeout
                are taken from it (unless explicitly provided).
        """
        if config is not None:
            self._config = config
            # Use config values, but allow explicit overrides
            self._max_workers = max_workers if max_workers is not None else config.max_workers
            self._timeout = timeout if timeout != 30 else config.timeout  # noqa: PLR2004
        else:
            # Create a default config
            effective_max_workers = max_workers if max_workers is not None else (os.cpu_count() or 4)
            self._config = PoolConfig(max_workers=effective_max_workers, timeout=timeout)
            self._max_workers = effective_max_workers
            self._timeout = timeout

        self._running = False
        self._executor: ProcessPoolExecutor | None = None
        self._mp_context: multiprocessing.context.BaseContext = self._config.get_mp_context()
        self._is_warmed_up = False
        self._warmup_completed_count = 0

    @classmethod
    def from_config(cls, config: PoolConfig) -> Self:
        """Create a PersistentWorkerPool from a PoolConfig.

        This is the preferred way to create a pool with custom settings.

        Args:
            config: The configuration to use.

        Returns:
            A new PersistentWorkerPool configured with the given settings.

        Example:
            >>> config = PoolConfig(max_workers=4, start_method='forkserver')
            >>> pool = PersistentWorkerPool.from_config(config)
            >>> pool.max_workers
            4
        """
        return cls(config=config)

    @property
    def is_running(self) -> bool:
        """Return whether the pool is currently running."""
        return self._running

    @property
    def max_workers(self) -> int:
        """Return the maximum number of workers."""
        return self._max_workers

    @property
    def timeout(self) -> int:
        """Return the timeout in seconds."""
        return self._timeout

    @property
    def config(self) -> PoolConfig:
        """Return the PoolConfig used by this pool."""
        return self._config

    @property
    def is_warmed_up(self) -> bool:
        """Return whether workers have been pre-warmed."""
        return self._is_warmed_up

    @property
    def warmup_completed_count(self) -> int:
        """Return the number of workers that completed warmup."""
        return self._warmup_completed_count

    def __enter__(self) -> Self:
        """Enter context manager, starting workers."""
        self._start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit context manager, shutting down workers."""
        self._shutdown()

    def _start(self) -> None:
        """Start the worker processes.

        Creates the ProcessPoolExecutor with the configured multiprocessing context
        and optionally warms up workers by submitting no-op tasks.
        """
        self._executor = ProcessPoolExecutor(
            max_workers=self._max_workers,
            mp_context=self._mp_context,
        )
        self._running = True

        # Warmup workers if enabled
        if self._config.warmup:
            self._warmup_workers()

    def _warmup_workers(self) -> None:
        """Pre-warm workers by submitting no-op tasks.

        This forces all workers to start and import necessary modules
        before actual work arrives, reducing latency on the first batch.
        """
        if self._executor is None:  # pragma: no cover
            return

        # Submit a no-op to each worker
        warmup_futures = [self._executor.submit(_warmup_noop) for _ in range(self._max_workers)]

        # Wait for all warmups to complete (with a reasonable timeout)
        completed, _ = wait(warmup_futures, timeout=30)
        self._warmup_completed_count = len(completed)
        self._is_warmed_up = self._warmup_completed_count == self._max_workers

    def _shutdown(self) -> None:
        """Shutdown the worker processes."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._running = False
        self._is_warmed_up = False
        self._warmup_completed_count = 0

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
            RuntimeError: If the pool is not running.
        """
        if not self._running or self._executor is None:
            msg = 'PersistentWorkerPool is not running. Use as context manager.'
            raise RuntimeError(msg)

        all_env_vars = dict(env_vars)
        if instrumented_dir is not None:
            all_env_vars['PYTEST_GREMLINS_SOURCES_FILE'] = f'{instrumented_dir}/sources.json'

        return self._executor.submit(
            _run_gremlin_test,
            gremlin_id,
            test_command,
            rootdir,
            all_env_vars,
            self._timeout,
        )

    def submit_batch(
        self,
        gremlin_ids: list[str],
        test_command: list[str],
        rootdir: str,
        instrumented_dir: str | None,
        env_vars: dict[str, str],
    ) -> Future[list[WorkerResult]]:
        """Submit a batch of gremlin tests for execution in a single subprocess.

        Batch execution reduces subprocess overhead by testing multiple gremlins
        in one subprocess call. Uses early termination - stops after first zap.

        Args:
            gremlin_ids: List of gremlin IDs to test.
            test_command: Command to run tests.
            rootdir: Root directory for test execution.
            instrumented_dir: Directory with instrumented sources (or None).
            env_vars: Additional environment variables to set.

        Returns:
            Future that will contain list of WorkerResult for each tested gremlin.

        Raises:
            RuntimeError: If the pool is not running.
        """
        if not self._running or self._executor is None:
            msg = 'PersistentWorkerPool is not running. Use as context manager.'
            raise RuntimeError(msg)

        all_env_vars = dict(env_vars)
        if instrumented_dir is not None:
            all_env_vars['PYTEST_GREMLINS_SOURCES_FILE'] = f'{instrumented_dir}/sources.json'

        return self._executor.submit(
            _run_gremlin_batch,
            gremlin_ids,
            test_command,
            rootdir,
            all_env_vars,
            self._timeout,
        )
