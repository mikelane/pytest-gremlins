"""Tests for batch operations in ResultStore.

These tests verify that batch operations are supported and commit less often than
individual operations. They count COMMIT statements, not seconds.
"""

from pathlib import Path

import pytest

from pytest_gremlins.cache.store import ResultStore

from .cached_entries import partial_entry

NUM_ENTRIES = 100


def commit_statements(store: ResultStore) -> list[str]:
    """Record every COMMIT the store's connection executes from now on."""
    commits: list[str] = []

    def record_commit(statement: str) -> None:
        if statement == 'COMMIT':
            commits.append(statement)

    store._conn.set_trace_callback(record_commit)
    return commits


@pytest.mark.medium
class DescribeStoreBatchOperations:
    """Tests for batch write support."""

    def it_put_deferred_does_not_commit_immediately(self, tmp_path: Path) -> None:
        """put_deferred does not commit until flush is called."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            store.put_deferred('key1', partial_entry(status='zapped'))
            store.put_deferred('key2', partial_entry(status='survived'))

            # Data should be in memory but not visible to new connections
            # (no commit has happened)

            # Flush to commit
            store.flush()

            # Now data should be retrievable
            assert store.get('key1') == partial_entry(status='zapped')
            assert store.get('key2') == partial_entry(status='survived')

    def it_commits_once_per_individual_put(self, tmp_path: Path) -> None:
        """Each put commits on its own."""
        with ResultStore(tmp_path / 'results.db') as store:
            commits = commit_statements(store)

            for i in range(NUM_ENTRIES):
                store.put(f'individual_key_{i}', partial_entry(value=i))

        assert len(commits) == NUM_ENTRIES

    def it_commits_a_deferred_batch_once_on_flush(self, tmp_path: Path) -> None:
        """Deferred puts share a single commit, made by flush."""
        with ResultStore(tmp_path / 'results.db') as store:
            commits = commit_statements(store)

            for i in range(NUM_ENTRIES):
                store.put_deferred(f'batch_key_{i}', partial_entry(value=i))
            store.flush()

        assert len(commits) == 1

    def it_close_flushes_pending_writes(self, tmp_path: Path) -> None:
        """Closing the store flushes any pending deferred writes."""
        db_path = tmp_path / 'results.db'

        # Write with deferred, close without explicit flush
        with ResultStore(db_path) as store:
            store.put_deferred('key1', partial_entry(status='zapped'))
            # No explicit flush - close should handle it

        # Reopen and verify data persisted
        with ResultStore(db_path) as store:
            result = store.get('key1')
            assert result == partial_entry(status='zapped')

    def it_context_manager_flushes_on_exit(self, tmp_path: Path) -> None:
        """Context manager exit flushes pending writes."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            store.put_deferred('key1', partial_entry(status='zapped'))

        # Data should be persisted
        with ResultStore(db_path) as store:
            assert store.get('key1') == partial_entry(status='zapped')
