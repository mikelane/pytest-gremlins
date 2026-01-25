"""Tests for ResultAggregator class.

These tests verify result collection, ordering, and error handling.
"""

from __future__ import annotations

import threading

from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


class TestResultAggregatorCreation:
    """Tests for ResultAggregator instantiation."""

    def test_creates_with_total_gremlins(self) -> None:
        """ResultAggregator stores total gremlin count."""
        aggregator = ResultAggregator(total_gremlins=10)
        assert aggregator.total_gremlins == 10

    def test_creates_empty(self) -> None:
        """New aggregator has no results."""
        aggregator = ResultAggregator(total_gremlins=10)
        assert aggregator.completed == 0
        assert aggregator.get_results() == []


class TestResultAggregatorAddResult:
    """Tests for adding results to aggregator."""

    def test_add_result_increments_completed(self) -> None:
        """Adding result increments completed count."""
        aggregator = ResultAggregator(total_gremlins=10)
        result = WorkerResult(
            gremlin_id='g001',
            status=GremlinResultStatus.ZAPPED,
        )
        aggregator.add_result(result)
        assert aggregator.completed == 1

    def test_add_multiple_results(self) -> None:
        """Can add multiple results."""
        aggregator = ResultAggregator(total_gremlins=10)
        for i in range(5):
            result = WorkerResult(
                gremlin_id=f'g{i:03d}',
                status=GremlinResultStatus.ZAPPED,
            )
            aggregator.add_result(result)
        assert aggregator.completed == 5

    def test_get_results_returns_all_added(self) -> None:
        """get_results returns all added results."""
        aggregator = ResultAggregator(total_gremlins=3)
        for i in range(3):
            result = WorkerResult(
                gremlin_id=f'g{i:03d}',
                status=GremlinResultStatus.ZAPPED,
            )
            aggregator.add_result(result)

        results = aggregator.get_results()
        assert len(results) == 3


class TestResultAggregatorOrdering:
    """Tests for result ordering."""

    def test_results_sorted_by_gremlin_id(self) -> None:
        """Results are sorted by gremlin_id."""
        aggregator = ResultAggregator(total_gremlins=5)

        # Add in non-sorted order
        for gid in ['g003', 'g001', 'g005', 'g002', 'g004']:
            result = WorkerResult(
                gremlin_id=gid,
                status=GremlinResultStatus.ZAPPED,
            )
            aggregator.add_result(result)

        results = aggregator.get_results()
        ids = [r.gremlin_id for r in results]
        assert ids == ['g001', 'g002', 'g003', 'g004', 'g005']


class TestResultAggregatorProgress:
    """Tests for progress reporting."""

    def test_get_progress_returns_completed_and_total(self) -> None:
        """get_progress returns (completed, total)."""
        aggregator = ResultAggregator(total_gremlins=10)
        assert aggregator.get_progress() == (0, 10)

        for i in range(3):
            result = WorkerResult(
                gremlin_id=f'g{i:03d}',
                status=GremlinResultStatus.ZAPPED,
            )
            aggregator.add_result(result)

        assert aggregator.get_progress() == (3, 10)

    def test_progress_percentage(self) -> None:
        """progress_percentage returns correct percentage."""
        aggregator = ResultAggregator(total_gremlins=10)
        assert aggregator.progress_percentage == 0.0

        for i in range(5):
            result = WorkerResult(
                gremlin_id=f'g{i:03d}',
                status=GremlinResultStatus.ZAPPED,
            )
            aggregator.add_result(result)

        assert aggregator.progress_percentage == 50.0


class TestResultAggregatorErrorHandling:
    """Tests for error handling."""

    def test_add_error_creates_error_result(self) -> None:
        """add_error creates result with ERROR status."""
        aggregator = ResultAggregator(total_gremlins=10)
        aggregator.add_error('g001', Exception('Worker crashed'))

        results = aggregator.get_results()
        assert len(results) == 1
        assert results[0].gremlin_id == 'g001'
        assert results[0].status == GremlinResultStatus.ERROR

    def test_add_error_increments_completed(self) -> None:
        """add_error increments completed count."""
        aggregator = ResultAggregator(total_gremlins=10)
        aggregator.add_error('g001', Exception('Worker crashed'))
        assert aggregator.completed == 1


class TestResultAggregatorThreadSafety:
    """Tests for thread-safe result collection."""

    def test_concurrent_add_results(self) -> None:
        """Multiple threads can add results concurrently."""
        aggregator = ResultAggregator(total_gremlins=100)
        threads = []

        def add_results(start: int, count: int) -> None:
            for i in range(start, start + count):
                result = WorkerResult(
                    gremlin_id=f'g{i:03d}',
                    status=GremlinResultStatus.ZAPPED,
                )
                aggregator.add_result(result)

        # Start 10 threads, each adding 10 results
        for i in range(10):
            t = threading.Thread(target=add_results, args=(i * 10, 10))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        assert aggregator.completed == 100
        results = aggregator.get_results()
        assert len(results) == 100

    def test_no_duplicate_results_from_concurrent_adds(self) -> None:
        """Concurrent adds don't create duplicates."""
        aggregator = ResultAggregator(total_gremlins=50)
        threads = []

        def add_results(start: int, count: int) -> None:
            for i in range(start, start + count):
                result = WorkerResult(
                    gremlin_id=f'g{i:03d}',
                    status=GremlinResultStatus.ZAPPED,
                )
                aggregator.add_result(result)

        for i in range(5):
            t = threading.Thread(target=add_results, args=(i * 10, 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        results = aggregator.get_results()
        ids = [r.gremlin_id for r in results]
        # No duplicates
        assert len(ids) == len(set(ids))


class TestResultAggregatorStatusCounts:
    """Tests for status count tracking."""

    def test_counts_zapped(self) -> None:
        """Tracks count of zapped gremlins."""
        aggregator = ResultAggregator(total_gremlins=10)
        for i in range(3):
            aggregator.add_result(
                WorkerResult(
                    gremlin_id=f'g{i:03d}',
                    status=GremlinResultStatus.ZAPPED,
                )
            )
        assert aggregator.zapped_count == 3

    def test_counts_survived(self) -> None:
        """Tracks count of survived gremlins."""
        aggregator = ResultAggregator(total_gremlins=10)
        for i in range(4):
            aggregator.add_result(
                WorkerResult(
                    gremlin_id=f'g{i:03d}',
                    status=GremlinResultStatus.SURVIVED,
                )
            )
        assert aggregator.survived_count == 4

    def test_counts_timeout(self) -> None:
        """Tracks count of timed out gremlins."""
        aggregator = ResultAggregator(total_gremlins=10)
        for i in range(2):
            aggregator.add_result(
                WorkerResult(
                    gremlin_id=f'g{i:03d}',
                    status=GremlinResultStatus.TIMEOUT,
                )
            )
        assert aggregator.timeout_count == 2

    def test_counts_error(self) -> None:
        """Tracks count of error gremlins."""
        aggregator = ResultAggregator(total_gremlins=10)
        aggregator.add_error('g001', Exception('crash'))
        aggregator.add_error('g002', Exception('crash'))
        assert aggregator.error_count == 2
