"""Performance tests for cache and store components that use SQLite.

These tests verify that cache/store operations are fast enough to provide
a net performance benefit during mutation testing. They use SQLite I/O
and are therefore categorized as MEDIUM tests.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore

from .cached_entries import partial_entry
from .commit_counter import (
    record_commits,
    record_statements,
)


@pytest.mark.medium
class DescribeCachePerformance:
    """Performance tests for cache operations."""

    def it_cache_lookup_runs_one_select_per_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each cache lookup is a single read query that writes and commits nothing."""
        cache_dir = tmp_path / '.gremlins_cache'

        statements = record_statements(monkeypatch)
        with IncrementalCache(cache_dir) as cache:
            for i in range(100):
                cache.cache_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                    result=partial_entry(status='zapped', killing_test='test_foo'),
                )
            statements.clear()
            for i in range(100):
                cache.get_cached_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                )

        assert [statement.split()[0] for statement in statements] == ['SELECT'] * 100

    def it_cache_write_commits_once_per_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each immediate cache write is durable on its own commit."""
        cache_dir = tmp_path / '.gremlins_cache'

        commits = record_commits(monkeypatch)
        with IncrementalCache(cache_dir) as cache:
            commits.clear()
            for i in range(100):
                cache.cache_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                    result=partial_entry(status='zapped', killing_test='test_foo'),
                )

        assert len(commits) == 100

    def it_cache_key_computation_touches_no_database(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Building cache keys is pure computation: no query runs and each gremlin gets its own key."""
        cache_dir = tmp_path / '.gremlins_cache'
        test_hashes = {'test_foo': 'hash_foo', 'test_bar': 'hash_bar', 'test_baz': 'hash_baz'}

        statements = record_statements(monkeypatch)
        with IncrementalCache(cache_dir) as cache:
            statements.clear()
            keys = {cache._build_cache_key(f'gremlin_{i}', 'source_hash_abc123', test_hashes) for i in range(1000)}

        assert (statements, len(keys)) == ([], 1000)


@pytest.mark.medium
class DescribeStorePerformance:
    """Performance tests for result store."""

    def it_batch_writes_commit_fewer_times_than_individual(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Batched writes use one commit where individual writes use one per entry."""
        individual_commits = record_commits(monkeypatch)
        with ResultStore(tmp_path / 'individual.db') as store:
            individual_commits.clear()
            for i in range(100):
                store.put(f'key_{i}', partial_entry(value=i))
        individual_commit_count = len(individual_commits)

        batch_commits = record_commits(monkeypatch)
        with ResultStore(tmp_path / 'batch.db') as store:
            batch_commits.clear()
            for i in range(100):
                store.put_deferred(f'key_{i}', partial_entry(value=i))
            store.flush()

        assert (individual_commit_count, len(batch_commits)) == (100, 1)

    def it_lookup_searches_the_primary_key_index(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each store lookup is one keyed SELECT that SQLite answers by index search, not a table scan."""
        db_path = tmp_path / 'results.db'

        statements = record_statements(monkeypatch)
        with ResultStore(db_path) as store:
            for i in range(1000):
                store.put(f'key_{i}', partial_entry(value=i))
            statements.clear()
            for i in range(100):
                store.get(f'key_{i}')

        with closing(sqlite3.connect(db_path)) as connection:
            plan = connection.execute(f'EXPLAIN QUERY PLAN {statements[0]}').fetchall()
        assert (statements[1], len(statements), plan[0][3].startswith('SEARCH')) == (
            "SELECT result_json FROM results WHERE cache_key = 'key_1'",
            100,
            True,
        )
