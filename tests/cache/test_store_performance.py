"""Performance tests for cache and store components that use SQLite.

These tests verify that cache/store operations are fast enough to provide
a net performance benefit during mutation testing. They use SQLite I/O
and are therefore categorized as MEDIUM tests.
"""

from pathlib import Path
import time

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore

from .commit_counter import count_commits


@pytest.mark.medium
class DescribeCachePerformance:
    """Performance tests for cache operations."""

    def it_cache_lookup_is_fast(self, tmp_path: Path) -> None:
        """Cache lookup completes in under 1ms per entry."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            # Store 100 results
            for i in range(100):
                cache.cache_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                    result={'status': 'zapped', 'killing_test': 'test_foo'},
                )

            # Time 100 cache lookups
            start = time.perf_counter()
            for i in range(100):
                cache.get_cached_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                )
            elapsed = time.perf_counter() - start

            # 100 lookups should take less than 100ms (1ms per lookup)
            assert elapsed < 0.1, f'Cache lookups took {elapsed * 1000:.1f}ms for 100 entries'

    def it_cache_write_commits_once_per_entry(self, tmp_path: Path) -> None:
        """Each immediate cache write is durable on its own commit."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            commits = count_commits(cache._store._conn)
            for i in range(100):
                cache.cache_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                    result={'status': 'zapped', 'killing_test': 'test_foo'},
                )

        assert len(commits) == 100

    def it_cache_key_computation_is_fast(self, tmp_path: Path) -> None:
        """Cache key computation completes in under 0.1ms per key."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            # Time 1000 key computations
            start = time.perf_counter()
            for i in range(1000):
                cache._build_cache_key(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash_abc123',
                    test_hashes={
                        'test_foo': 'hash_foo',
                        'test_bar': 'hash_bar',
                        'test_baz': 'hash_baz',
                    },
                )
            elapsed = time.perf_counter() - start

            # 1000 key computations should take less than 100ms (0.1ms per key)
            assert elapsed < 0.1, f'Key computation took {elapsed * 1000:.1f}ms for 1000 keys'


@pytest.mark.medium
class DescribeStorePerformance:
    """Performance tests for result store."""

    def it_batch_writes_commit_fewer_times_than_individual(self, tmp_path: Path) -> None:
        """Batched writes use one commit where individual writes use one per entry."""
        with ResultStore(tmp_path / 'individual.db') as store:
            individual_commits = count_commits(store._conn)
            for i in range(100):
                store.put(f'key_{i}', {'value': i})

        with ResultStore(tmp_path / 'batch.db') as store:
            batch_commits = count_commits(store._conn)
            for i in range(100):
                store.put_deferred(f'key_{i}', {'value': i})
            store.flush()

        assert (len(individual_commits), len(batch_commits)) == (100, 1)

    def it_lookup_with_index_is_fast(self, tmp_path: Path) -> None:
        """Cache lookups with SQLite index complete in under 1ms."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            # Populate with 1000 entries
            for i in range(1000):
                store.put(f'key_{i}', {'value': i})

            # Time lookups (should use PRIMARY KEY index)
            start = time.perf_counter()
            for i in range(100):
                store.get(f'key_{i}')
            elapsed = time.perf_counter() - start

            # 100 lookups should take less than 100ms
            assert elapsed < 0.1, f'Store lookups took {elapsed * 1000:.1f}ms for 100 entries'
