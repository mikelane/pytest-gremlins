"""Result aggregation for parallel gremlin execution.

This module provides the ResultAggregator class that collects and merges
results from parallel worker processes.
"""

from __future__ import annotations

import threading

from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


class ResultAggregator:
    """Aggregates results from parallel worker processes.

    Thread-safe collection of results with progress tracking and status counts.
    Results are stored as they arrive and can be retrieved sorted by gremlin ID.

    Attributes:
        total_gremlins: Total number of gremlins being tested.
        completed: Number of gremlins that have been processed.

    Example:
        >>> aggregator = ResultAggregator(total_gremlins=100)
        >>> aggregator.add_result(WorkerResult('g001', GremlinResultStatus.ZAPPED))
        >>> progress = aggregator.get_progress()  # (1, 100)
    """

    def __init__(self, total_gremlins: int) -> None:
        """Initialize the result aggregator.

        Args:
            total_gremlins: Total number of gremlins to be tested.
        """
        self._total_gremlins = total_gremlins
        self._results: list[WorkerResult] = []
        self._lock = threading.Lock()
        self._zapped = 0
        self._survived = 0
        self._timeout = 0
        self._error = 0

    @property
    def total_gremlins(self) -> int:
        """Return the total number of gremlins."""
        return self._total_gremlins

    @property
    def completed(self) -> int:
        """Return the number of completed results."""
        with self._lock:
            return len(self._results)

    @property
    def zapped_count(self) -> int:
        """Return the number of zapped gremlins."""
        with self._lock:
            return self._zapped

    @property
    def survived_count(self) -> int:
        """Return the number of survived gremlins."""
        with self._lock:
            return self._survived

    @property
    def timeout_count(self) -> int:
        """Return the number of timed out gremlins."""
        with self._lock:
            return self._timeout

    @property
    def error_count(self) -> int:
        """Return the number of error gremlins."""
        with self._lock:
            return self._error

    @property
    def progress_percentage(self) -> float:
        """Return progress as a percentage.

        Returns:
            Progress from 0.0 to 100.0.
        """
        if self._total_gremlins == 0:
            return 0.0
        with self._lock:
            return (len(self._results) / self._total_gremlins) * 100

    def add_result(self, result: WorkerResult) -> None:
        """Add a result from a worker.

        Thread-safe method to add a result to the aggregator.

        Args:
            result: The worker result to add.
        """
        with self._lock:
            self._results.append(result)
            self._update_status_count(result.status)

    def add_error(self, gremlin_id: str, error: Exception) -> None:  # noqa: ARG002
        """Record an error for a gremlin.

        Creates an ERROR status result when a worker fails.

        Args:
            gremlin_id: The ID of the gremlin that failed.
            error: The exception that occurred.
        """
        result = WorkerResult(
            gremlin_id=gremlin_id,
            status=GremlinResultStatus.ERROR,
        )
        self.add_result(result)

    def get_results(self) -> list[WorkerResult]:
        """Get all results sorted by gremlin ID.

        Returns:
            List of WorkerResult objects sorted by gremlin_id.
        """
        with self._lock:
            return sorted(self._results, key=lambda r: r.gremlin_id)

    def get_progress(self) -> tuple[int, int]:
        """Get progress as (completed, total).

        Returns:
            Tuple of (completed count, total count).
        """
        with self._lock:
            return (len(self._results), self._total_gremlins)

    def _update_status_count(self, status: GremlinResultStatus) -> None:
        """Update status counts. Must be called with lock held.

        Args:
            status: The status to count.
        """
        if status == GremlinResultStatus.ZAPPED:
            self._zapped += 1
        elif status == GremlinResultStatus.SURVIVED:
            self._survived += 1
        elif status == GremlinResultStatus.TIMEOUT:
            self._timeout += 1
        elif status == GremlinResultStatus.ERROR:
            self._error += 1
        else:  # pragma: no cover
            msg = f'Unexpected gremlin status: {status}'
            raise ValueError(msg)
