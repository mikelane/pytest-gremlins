"""Tests for BatchExecutor - the core batch execution coordinator.

BatchExecutor coordinates batch execution of gremlin tests to reduce
subprocess overhead. It divides gremlins into batches, distributes them
across workers, and aggregates results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.parallel.batch_executor import BatchExecutor
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestBatchExecutorCreation:
    """Tests for BatchExecutor instantiation."""

    def test_creates_with_default_batch_size(self) -> None:
        """BatchExecutor defaults to batch size of 10."""
        executor = BatchExecutor()
        assert executor.batch_size == 10

    def test_creates_with_specified_batch_size(self) -> None:
        """BatchExecutor respects specified batch size."""
        executor = BatchExecutor(batch_size=5)
        assert executor.batch_size == 5

    def test_creates_with_workers(self) -> None:
        """BatchExecutor stores the specified worker count."""
        executor = BatchExecutor(max_workers=4)
        assert executor.max_workers == 4


@pytest.mark.small
class TestBatchExecutorPartitioning:
    """Tests for how BatchExecutor partitions gremlins into batches."""

    def test_partitions_gremlins_into_batches(self) -> None:
        """Gremlins are partitioned into batches of specified size."""
        executor = BatchExecutor(batch_size=3)
        gremlin_ids = ['g001', 'g002', 'g003', 'g004', 'g005']

        batches = executor.partition(gremlin_ids)

        assert len(batches) == 2
        assert batches[0] == ['g001', 'g002', 'g003']
        assert batches[1] == ['g004', 'g005']

    def test_empty_gremlin_list_returns_empty_batches(self) -> None:
        """Empty gremlin list returns empty batches."""
        executor = BatchExecutor(batch_size=3)

        batches = executor.partition([])

        assert batches == []

    def test_batch_size_one_creates_single_gremlin_batches(self) -> None:
        """Batch size 1 creates one batch per gremlin (no batching)."""
        executor = BatchExecutor(batch_size=1)
        gremlin_ids = ['g001', 'g002', 'g003']

        batches = executor.partition(gremlin_ids)

        assert len(batches) == 3
        assert batches == [['g001'], ['g002'], ['g003']]

    def test_gremlins_less_than_batch_size_creates_one_batch(self) -> None:
        """When gremlins < batch_size, creates single batch."""
        executor = BatchExecutor(batch_size=10)
        gremlin_ids = ['g001', 'g002', 'g003']

        batches = executor.partition(gremlin_ids)

        assert len(batches) == 1
        assert batches[0] == ['g001', 'g002', 'g003']


@pytest.mark.small
class TestBatchExecutorExecution:
    """Tests for BatchExecutor execution."""

    def test_execute_returns_results_for_all_gremlins(self, tmp_path: Path) -> None:
        """Execute returns results for all tested gremlins."""
        executor = BatchExecutor(batch_size=2, max_workers=1)

        results = executor.execute(
            gremlin_ids=['g001', 'g002', 'g003'],
            test_command=['python', '-c', 'pass'],
            rootdir=str(tmp_path),
            instrumented_dir=None,
            env_vars={},
        )

        # All 3 gremlins survive (tests pass)
        assert len(results) == 3
        assert all(isinstance(r, WorkerResult) for r in results)
        assert {r.gremlin_id for r in results} == {'g001', 'g002', 'g003'}

    def test_execute_with_early_termination_batch(self, tmp_path: Path) -> None:
        """Execute handles early termination within batches."""
        script = tmp_path / 'test_script.py'
        script.write_text("""
import os
import sys
gremlin = os.environ.get('ACTIVE_GREMLIN')
# g002 is detected (killed)
sys.exit(1 if gremlin == 'g002' else 0)
""")

        executor = BatchExecutor(batch_size=5, max_workers=1)

        results = executor.execute(
            gremlin_ids=['g001', 'g002', 'g003'],
            test_command=['python', str(script)],
            rootdir=str(tmp_path),
            instrumented_dir=None,
            env_vars={},
        )

        # g001 survives, g002 is zapped, g003 is skipped (within same batch)
        assert len(results) == 2
        assert results[0].gremlin_id == 'g001'
        assert results[0].status == GremlinResultStatus.SURVIVED
        assert results[1].gremlin_id == 'g002'
        assert results[1].status == GremlinResultStatus.ZAPPED

    def test_execute_with_empty_gremlin_ids_returns_empty_list(self, tmp_path: Path) -> None:
        """Execute returns empty list when no gremlins to test."""
        executor = BatchExecutor(batch_size=5, max_workers=1)

        results = executor.execute(
            gremlin_ids=[],
            test_command=['python', '-c', 'pass'],
            rootdir=str(tmp_path),
            instrumented_dir=None,
            env_vars={},
        )

        assert results == []

    def test_execute_sets_sources_file_env_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """Execute sets PYTEST_GREMLINS_SOURCES_FILE when instrumented_dir is provided."""
        script = tmp_path / 'test_script.py'
        script.write_text("""
import os
import sys
# Check that the sources file env var is set
sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE', '')
if 'instrumented/sources.json' not in sources_file:
    print(f"SOURCES_FILE not set correctly: {sources_file}")
    sys.exit(1)
sys.exit(0)
""")

        executor = BatchExecutor(batch_size=5, max_workers=1)

        results = executor.execute(
            gremlin_ids=['g001'],
            test_command=['python', str(script)],
            rootdir=str(tmp_path),
            instrumented_dir=str(tmp_path / 'instrumented'),
            env_vars={},
        )

        # Test passes if sources file was set correctly
        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.SURVIVED
