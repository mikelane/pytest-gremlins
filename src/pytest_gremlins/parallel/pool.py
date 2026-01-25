"""Worker pool manager for parallel gremlin execution.

This module provides the WorkerPool class that manages a pool of worker processes
for running mutation tests in parallel.

Note: This module uses ProcessPoolExecutor which internally uses pickle for
inter-process communication. The data being serialized is entirely under our
control (WorkerResult dataclass with primitive types) - no untrusted external
content is ever deserialized.
"""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
import os
import subprocess
import time
from typing import Self

from pytest_gremlins.reporting.results import GremlinResultStatus


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
    """

    gremlin_id: str
    status: GremlinResultStatus
    killing_test: str | None = None
    execution_time_ms: float | None = None


def _run_gremlin_test(
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
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.ZAPPED,
                killing_test='unknown',
                execution_time_ms=execution_time_ms,
            )
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.SURVIVED,
            execution_time_ms=execution_time_ms,
        )
    except subprocess.TimeoutExpired:
        execution_time_ms = (time.monotonic() - start_time) * 1000
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.TIMEOUT,
            execution_time_ms=execution_time_ms,
        )
    except Exception:
        execution_time_ms = (time.monotonic() - start_time) * 1000
        return WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.ERROR,
            execution_time_ms=execution_time_ms,
        )


class WorkerPool:
    """Manages a pool of worker processes for parallel mutation testing.

    The worker pool wraps a ProcessPoolExecutor and provides lifecycle management
    for parallel gremlin execution. Workers are isolated processes that each set
    their own ACTIVE_GREMLIN environment variable.

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
    ) -> None:
        """Initialize the worker pool.

        Args:
            max_workers: Maximum number of worker processes. Defaults to CPU count.
            timeout: Timeout in seconds for individual tests. Defaults to 30.
        """
        self._max_workers = max_workers if max_workers is not None else (os.cpu_count() or 4)
        self._timeout = timeout
        self._executor: ProcessPoolExecutor | None = None
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
        self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
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
            all_env_vars['PYTEST_GREMLINS_SOURCES_FILE'] = f'{instrumented_dir}/sources.json'

        return self._executor.submit(
            _run_gremlin_test,
            gremlin_id,
            test_command,
            rootdir,
            all_env_vars,
            self._timeout,
        )
