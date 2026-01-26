"""Tests for batch operations in IncrementalCache."""

import time
from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache


@pytest.mark.small
class TestIncrementalCacheBatchOperations:
    """Tests for batch cache write support."""

    def test_cache_result_deferred_batches_writes(self, tmp_path: Path) -> None:
        """cache_result_deferred batches writes for better performance."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100

        with IncrementalCache(cache_dir) as cache:
            # Time deferred writes
            start = time.perf_counter()
            for i in range(num_gremlins):
                cache.cache_result_deferred(
                    f'gremlin_{i}',
                    'source_hash',
                    {'test': 'hash'},
                    {'status': 'zapped'},
                )
            cache.flush()
            deferred_time = time.perf_counter() - start

        # Verify all writes persisted
        with IncrementalCache(cache_dir) as cache:
            for i in range(num_gremlins):
                result = cache.get_cached_result(f'gremlin_{i}', 'source_hash', {'test': 'hash'})
                assert result == {'status': 'zapped'}

        # Deferred writes should be fast (< 100ms for 100 entries)
        assert deferred_time < 0.1, f'Deferred writes took {deferred_time * 1000:.1f}ms for {num_gremlins} entries'

    def test_close_flushes_deferred_writes(self, tmp_path: Path) -> None:
        """Closing the cache flushes any pending deferred writes."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            cache.cache_result_deferred('g1', 'src', {'t': 'h'}, {'status': 'zapped'})
            # No explicit flush

        # Data should be persisted
        with IncrementalCache(cache_dir) as cache:
            result = cache.get_cached_result('g1', 'src', {'t': 'h'})
            assert result == {'status': 'zapped'}
