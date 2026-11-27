"""Batch executor that groups gremlins into worker tasks.

Batching groups gremlins into worker tasks. It does not reduce subprocesses:
the plugin's batch path still starts one bootstrap subprocess per gremlin
(100 gremlins with batch_size=10 = 10 worker tasks, still 100 subprocesses).
Making a batch share one subprocess is tracked in issue #538.

The BatchExecutor coordinates:
1. Partitioning gremlins into batches
2. Distributing batches across workers
3. Aggregating results from all batches

Optimizations (PR #52):
- Integration with PoolConfig for configurable start method and warmup
- Uses optimal multiprocessing context for the platform
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import (
    FIRST_COMPLETED,
    wait,
)
import os
from typing import (
    TYPE_CHECKING,
    Self,
)

from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool_config import PoolConfig

if TYPE_CHECKING:
    from pytest_gremlins.parallel.pool import WorkerResult


class BatchExecutor:
    """Coordinates batch execution of gremlin tests.

    Partitions gremlins into batches and hands each batch to a worker as
    one task. Gremlins in a batch are tested sequentially by that worker.

    Supports PoolConfig for advanced configuration including process
    start method selection and worker warmup.

    Attributes:
        batch_size: Number of gremlins per batch.
        max_workers: Maximum number of parallel worker processes.
        config: The PoolConfig used to configure the underlying pool.

    Example:
        >>> config = PoolConfig(max_workers=4, batch_size=20, warmup=True)  # doctest: +SKIP
        >>> executor = BatchExecutor.from_config(config)  # doctest: +SKIP
        >>> results = executor.execute(['g001', 'g002'], ['pytest'], '.', None, {})  # doctest: +SKIP
    """

    def __init__(
        self,
        batch_size: int = 10,
        max_workers: int | None = None,
        timeout: int = 30,
        *,
        config: PoolConfig | None = None,
    ) -> None:
        """Initialize the batch executor.

        Args:
            batch_size: Number of gremlins per batch. Defaults to 10.
            max_workers: Maximum number of worker processes. Defaults to CPU count.
            timeout: Timeout in seconds for individual gremlin tests.
            config: Optional PoolConfig. If provided, batch_size, max_workers,
                and timeout are taken from it (unless explicitly provided).
        """
        if config is not None:
            self._config = config
            # Use config values, but allow explicit overrides
            self._batch_size = batch_size if batch_size != 10 else config.batch_size  # noqa: PLR2004
            self._max_workers = max_workers if max_workers is not None else config.max_workers
            self._timeout = timeout if timeout != 30 else config.timeout  # noqa: PLR2004
        else:
            # Create a default config
            effective_max_workers = max_workers if max_workers is not None else (os.cpu_count() or 4)
            self._config = PoolConfig(
                max_workers=effective_max_workers,
                timeout=timeout,
                batch_size=batch_size,
            )
            self._batch_size = batch_size
            self._max_workers = effective_max_workers
            self._timeout = timeout

    @classmethod
    def from_config(cls, config: PoolConfig) -> Self:
        """Create a BatchExecutor from a PoolConfig.

        This is the preferred way to create an executor with custom settings.

        Args:
            config: The configuration to use.

        Returns:
            A new BatchExecutor configured with the given settings.

        Example:
            >>> config = PoolConfig(max_workers=4, batch_size=20)
            >>> executor = BatchExecutor.from_config(config)
            >>> executor.batch_size
            20
        """
        return cls(config=config)

    @property
    def batch_size(self) -> int:
        """Return the batch size."""
        return self._batch_size

    @property
    def max_workers(self) -> int:
        """Return the maximum number of workers."""
        return self._max_workers

    @property
    def config(self) -> PoolConfig:
        """Return the PoolConfig used by this executor."""
        return self._config

    def partition(self, gremlin_ids: list[str]) -> list[list[str]]:
        """Partition gremlin IDs into batches.

        Args:
            gremlin_ids: List of gremlin IDs to partition.

        Returns:
            List of batches, where each batch is a list of gremlin IDs.
        """
        if not gremlin_ids:
            return []

        batches: list[list[str]] = []
        for i in range(0, len(gremlin_ids), self._batch_size):
            batch = gremlin_ids[i : i + self._batch_size]
            batches.append(batch)

        return batches

    def execute(
        self,
        gremlin_ids: list[str],
        test_command: list[str],
        rootdir: str,
        instrumented_dir: str | None,
        env_vars: dict[str, str],
    ) -> list[WorkerResult]:
        """Execute gremlin tests in batches and return every result at once.

        Args:
            gremlin_ids: List of gremlin IDs to test.
            test_command: Command to run tests.
            rootdir: Root directory for test execution.
            instrumented_dir: Directory with instrumented sources (or None).
            env_vars: Additional environment variables to set.

        Returns:
            List of WorkerResult for each tested gremlin.
        """
        return [
            result
            for batch_results in self.execute_batches(gremlin_ids, test_command, rootdir, instrumented_dir, env_vars)
            for result in batch_results
        ]

    def execute_batches(
        self,
        gremlin_ids: list[str],
        test_command: list[str],
        rootdir: str,
        instrumented_dir: str | None,
        env_vars: dict[str, str],
        *,
        idle_tick_seconds: float | None = None,
    ) -> Iterator[list[WorkerResult]]:
        """Execute gremlin tests in batches, yielding each batch's results as that batch finishes.

        Creates a PersistentWorkerPool using the configured PoolConfig,
        partitions gremlins into batches, and executes them in parallel. A caller that
        handles each yielded batch at once (caching its verdicts, say) keeps that work
        if the run is interrupted before the last batch returns (#979).

        Args:
            gremlin_ids: List of gremlin IDs to test.
            test_command: Command to run tests.
            rootdir: Root directory for test execution.
            instrumented_dir: Directory with instrumented sources (or None).
            env_vars: Additional environment variables to set.
            idle_tick_seconds: When set, an empty list is yielded each time this long passes with no batch
                finishing, so a caller can run its timers (a periodic cache flush) while a slow batch runs.

        Yields:
            The WorkerResult list of one batch, in the order batches complete; an empty list on an idle tick.
        """
        batches = self.partition(gremlin_ids)

        if not batches:
            return

        pool = PersistentWorkerPool.from_config(self._config)

        with pool:
            futures = {
                pool.submit_batch(
                    gremlin_ids=batch,
                    test_command=test_command,
                    rootdir=rootdir,
                    instrumented_dir=instrumented_dir,
                    env_vars=env_vars,
                ): batch
                for batch in batches
            }

            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=idle_tick_seconds, return_when=FIRST_COMPLETED)
                if not done:
                    yield []
                for future in done:
                    yield future.result()
