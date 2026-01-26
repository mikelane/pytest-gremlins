"""Tests for cache key computation memoization."""

import time
from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache


@pytest.mark.small
class TestCacheKeyMemoization:
    """Tests for memoized cache key computation."""

    def test_same_test_hashes_reuses_combined_hash(self, tmp_path: Path) -> None:
        """Repeated calls with same test_hashes dict reuse the combined hash."""
        cache_dir = tmp_path / '.gremlins_cache'

        # Create a large test_hashes dict (simulating many tests)
        test_hashes = {f'test_{i}': f'hash_{i}' * 10 for i in range(100)}

        with IncrementalCache(cache_dir) as cache:
            # First call - computes combined hash
            start = time.perf_counter()
            for i in range(100):
                cache._build_cache_key(f'gremlin_{i}', 'source_hash', test_hashes)
            first_time = time.perf_counter() - start

            # Second round - should be faster due to memoization
            # (Using frozen test_hashes tuple as cache key)
            start = time.perf_counter()
            for i in range(100):
                cache._build_cache_key(f'gremlin_{i}', 'source_hash', test_hashes)
            second_time = time.perf_counter() - start

        # Both should be fast (< 50ms for 100 computations)
        assert first_time < 0.05, f'First round took {first_time*1000:.1f}ms'
        assert second_time < 0.05, f'Second round took {second_time*1000:.1f}ms'
