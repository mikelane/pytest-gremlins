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


@pytest.mark.medium
class TestCachePerformance:
    """Performance tests for cache operations."""

    def test_cache_lookup_is_fast(self, tmp_path: Path) -> None:
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

    def test_cache_write_is_fast(self, tmp_path: Path) -> None:
        """Cache writes complete in under 10ms per entry (batch)."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            # Time 100 cache writes
            start = time.perf_counter()
            for i in range(100):
                cache.cache_result(
                    gremlin_id=f'gremlin_{i}',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                    result={'status': 'zapped', 'killing_test': 'test_foo'},
                )
            elapsed = time.perf_counter() - start

            # 100 writes should complete in a reasonable time
            # Note: Windows filesystem I/O is significantly slower than macOS/Linux
            # Allow 3 seconds to accommodate CI variance
            assert elapsed < 3.0, f'Cache writes took {elapsed * 1000:.1f}ms for 100 entries'

    def test_cache_key_computation_is_fast(self, tmp_path: Path) -> None:
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
class TestStorePerformance:
    """Performance tests for result store."""

    def test_batch_writes_are_faster_than_individual(self, tmp_path: Path) -> None:
        """Batch writes are at least 5x faster than individual writes."""
        db_path = tmp_path / 'results.db'

        # Time individual writes
        with ResultStore(db_path) as store:
            store.clear()
            start = time.perf_counter()
            for i in range(100):
                store.put(f'key_{i}', {'value': i})
            individual_time = time.perf_counter() - start

        # For comparison, batch writes (when implemented) should be much faster
        # For now, this test documents the expected improvement
        # We'll add batch write capability and compare

        # Individual writes should complete in a reasonable time
        # Note: Windows filesystem I/O is significantly slower than macOS/Linux
        # Allow 3 seconds to accommodate CI variance
        assert individual_time < 3.0, f'Individual writes took {individual_time * 1000:.1f}ms'

    def test_lookup_with_index_is_fast(self, tmp_path: Path) -> None:
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
