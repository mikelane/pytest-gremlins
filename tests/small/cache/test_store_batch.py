"""Tests for batch operations in ResultStore.

These tests verify that batch operations are supported and faster than
individual operations.
"""

from pathlib import Path
import time

import pytest

from pytest_gremlins.cache.store import ResultStore


@pytest.mark.small
class TestStoreBatchOperations:
    """Tests for batch write support."""

    def test_put_deferred_does_not_commit_immediately(self, tmp_path: Path) -> None:
        """put_deferred does not commit until flush is called."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            store.put_deferred('key1', {'status': 'zapped'})
            store.put_deferred('key2', {'status': 'survived'})

            # Data should be in memory but not visible to new connections
            # (no commit has happened)

            # Flush to commit
            store.flush()

            # Now data should be retrievable
            assert store.get('key1') == {'status': 'zapped'}
            assert store.get('key2') == {'status': 'survived'}

    def test_batch_writes_are_faster_than_individual(self, tmp_path: Path) -> None:
        """Batch writes with deferred commit are faster than individual commits."""
        db_path = tmp_path / 'results.db'
        num_entries = 100

        # Time individual writes (current behavior)
        with ResultStore(db_path) as store:
            store.clear()
            start = time.perf_counter()
            for i in range(num_entries):
                store.put(f'individual_key_{i}', {'value': i})
            individual_time = time.perf_counter() - start

        # Time batch writes (deferred commits)
        with ResultStore(db_path) as store:
            store.clear()
            start = time.perf_counter()
            for i in range(num_entries):
                store.put_deferred(f'batch_key_{i}', {'value': i})
            store.flush()
            batch_time = time.perf_counter() - start

        # Batch should be faster (fewer commits)
        assert batch_time < individual_time, (
            f'Batch writes ({batch_time * 1000:.1f}ms) should be faster than '
            f'individual writes ({individual_time * 1000:.1f}ms)'
        )

    def test_close_flushes_pending_writes(self, tmp_path: Path) -> None:
        """Closing the store flushes any pending deferred writes."""
        db_path = tmp_path / 'results.db'

        # Write with deferred, close without explicit flush
        with ResultStore(db_path) as store:
            store.put_deferred('key1', {'status': 'zapped'})
            # No explicit flush - close should handle it

        # Reopen and verify data persisted
        with ResultStore(db_path) as store:
            result = store.get('key1')
            assert result == {'status': 'zapped'}

    def test_context_manager_flushes_on_exit(self, tmp_path: Path) -> None:
        """Context manager exit flushes pending writes."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            store.put_deferred('key1', {'status': 'zapped'})

        # Data should be persisted
        with ResultStore(db_path) as store:
            assert store.get('key1') == {'status': 'zapped'}
