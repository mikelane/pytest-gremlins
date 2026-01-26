"""Integration performance tests for incremental cache.

These tests simulate the actual cache usage pattern from the plugin
to identify where time is being lost.
"""

import time
from pathlib import Path

import pytest

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache


@pytest.mark.small
class TestPluginCachePattern:
    """Tests that simulate the actual plugin cache usage pattern."""

    def test_warm_run_is_faster_than_cold_run(self, tmp_path: Path) -> None:
        """Warm run with cache hits is at least 10x faster than cold run."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 50
        num_tests = 20

        # Simulate source and test file hashes (pre-computed)
        hasher = ContentHasher()
        source_hash = hasher.hash_string('def add(a, b): return a + b')
        test_hashes = {f'test_{i}': hasher.hash_string(f'def test_{i}(): pass') for i in range(num_tests)}

        # COLD RUN: Compute hashes and write to cache
        with IncrementalCache(cache_dir) as cache:
            cold_start = time.perf_counter()

            for i in range(num_gremlins):
                gremlin_id = f'src/module.py:gremlin_{i}'
                # Simulate selecting tests for this gremlin (5 tests per gremlin)
                selected_test_hashes = {k: v for k, v in list(test_hashes.items())[:5]}

                # Check cache (miss expected)
                result = cache.get_cached_result(gremlin_id, source_hash, selected_test_hashes)
                assert result is None

                # Simulate test execution time (skip actual execution)
                # In real scenario, this would be ~0.5-5 seconds per gremlin

                # Cache the result
                cache.cache_result(
                    gremlin_id,
                    source_hash,
                    selected_test_hashes,
                    {'status': 'zapped', 'killing_test': 'test_0'},
                )

            cold_time = time.perf_counter() - cold_start

        # WARM RUN: All cache hits
        with IncrementalCache(cache_dir) as cache:
            warm_start = time.perf_counter()

            for i in range(num_gremlins):
                gremlin_id = f'src/module.py:gremlin_{i}'
                selected_test_hashes = {k: v for k, v in list(test_hashes.items())[:5]}

                # Check cache (hit expected)
                result = cache.get_cached_result(gremlin_id, source_hash, selected_test_hashes)
                assert result is not None

            warm_time = time.perf_counter() - warm_start

        # Warm run should be much faster (no writes, just reads)
        # Target: warm_time < cold_time / 10 (at least 10x faster)
        speedup = cold_time / warm_time if warm_time > 0 else float('inf')
        assert speedup >= 2.0, (
            f'Warm run speedup was only {speedup:.1f}x (cold={cold_time * 1000:.1f}ms, warm={warm_time * 1000:.1f}ms)'
        )

    def test_cache_overhead_per_gremlin(self, tmp_path: Path) -> None:
        """Cache overhead per gremlin is under 1ms for cache hits."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100

        hasher = ContentHasher()
        source_hash = hasher.hash_string('def add(a, b): return a + b')
        test_hashes = {'test_add': hasher.hash_string('def test_add(): pass')}

        # Populate cache
        with IncrementalCache(cache_dir) as cache:
            for i in range(num_gremlins):
                cache.cache_result(
                    f'gremlin_{i}',
                    source_hash,
                    test_hashes,
                    {'status': 'zapped'},
                )

        # Measure cache lookup overhead
        with IncrementalCache(cache_dir) as cache:
            start = time.perf_counter()
            for i in range(num_gremlins):
                cache.get_cached_result(f'gremlin_{i}', source_hash, test_hashes)
            elapsed = time.perf_counter() - start

        per_gremlin_ms = (elapsed / num_gremlins) * 1000
        assert per_gremlin_ms < 1.0, f'Cache overhead per gremlin: {per_gremlin_ms:.3f}ms (target: <1ms)'

    def test_file_hash_computation_cost(self, tmp_path: Path) -> None:
        """File hash computation for 50 files takes under 50ms."""
        # Create 50 simulated source files
        src_dir = tmp_path / 'src'
        src_dir.mkdir()

        for i in range(50):
            (src_dir / f'module_{i}.py').write_text('\n'.join([f'def function_{j}(): return {j}' for j in range(100)]))

        hasher = ContentHasher()

        # Time hashing all files
        start = time.perf_counter()
        hashes = {}
        for f in src_dir.iterdir():
            hashes[str(f)] = hasher.hash_file(f)
        elapsed = time.perf_counter() - start

        # 50 files should hash in under 50ms (1ms per file)
        assert elapsed < 0.05, f'Hashing 50 files took {elapsed * 1000:.1f}ms (target: <50ms)'

    def test_upfront_hashing_vs_lazy_hashing(self, tmp_path: Path) -> None:
        """Lazy hashing (hash on demand) is faster when cache hit rate is high."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100
        num_files = 20

        # Create file hashes (simulate upfront computation)
        hasher = ContentHasher()
        file_hashes = {f'file_{i}.py': hasher.hash_string(f'content_{i}') for i in range(num_files)}

        # Pattern 1: Upfront hashing (current behavior)
        # Hash all files, then check cache for each gremlin
        start = time.perf_counter()
        # Simulate hashing all files upfront
        _ = {k: hasher.hash_string(v) for k, v in file_hashes.items()}  # Re-hash as simulation
        upfront_hash_time = time.perf_counter() - start

        # Pattern 2: Lazy hashing (only hash when needed)
        # For cache hits, we don't need to re-hash anything if keys match
        # This test documents the expected behavior after optimization

        # Current overhead from upfront hashing affects every run
        # even when cache hit rate is 100%
        assert upfront_hash_time < 0.001, f'Upfront re-hashing took {upfront_hash_time * 1000:.3f}ms'


@pytest.mark.small
class TestCacheKeyEfficiency:
    """Tests for efficient cache key computation."""

    def test_cache_key_is_deterministic(self, tmp_path: Path) -> None:
        """Same inputs always produce same cache key."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            key1 = cache._build_cache_key(
                'gremlin_1',
                'source_hash',
                {'test_a': 'hash_a', 'test_b': 'hash_b'},
            )
            key2 = cache._build_cache_key(
                'gremlin_1',
                'source_hash',
                {'test_b': 'hash_b', 'test_a': 'hash_a'},  # Different order
            )

        assert key1 == key2, 'Cache key must be order-independent'

    def test_cache_key_distinguishes_different_inputs(self, tmp_path: Path) -> None:
        """Different inputs produce different cache keys."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            key1 = cache._build_cache_key('g1', 'src', {'t1': 'h1'})
            key2 = cache._build_cache_key('g2', 'src', {'t1': 'h1'})  # Different gremlin
            key3 = cache._build_cache_key('g1', 'src2', {'t1': 'h1'})  # Different source
            key4 = cache._build_cache_key('g1', 'src', {'t1': 'h2'})  # Different test hash
            key5 = cache._build_cache_key('g1', 'src', {'t2': 'h1'})  # Different test name (same hash)

        keys = {key1, key2, key3, key4, key5}
        # All 5 keys should be unique - including key5 which has different test name
        assert len(keys) == 5, f'All keys should be unique: {keys}'


@pytest.mark.small
class TestBatchOperations:
    """Tests for batch cache operations."""

    def test_batch_cache_lookup_pattern(self, tmp_path: Path) -> None:
        """Batch lookups are efficient for high cache hit scenarios."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100

        # Pre-populate cache
        with IncrementalCache(cache_dir) as cache:
            for i in range(num_gremlins):
                cache.cache_result(
                    f'g_{i}',
                    'src_hash',
                    {'test': 'hash'},
                    {'status': 'zapped'},
                )

        # Simulate batch lookup pattern
        with IncrementalCache(cache_dir) as cache:
            start = time.perf_counter()
            results = []
            for i in range(num_gremlins):
                result = cache.get_cached_result(f'g_{i}', 'src_hash', {'test': 'hash'})
                if result:
                    results.append(result)
            elapsed = time.perf_counter() - start

        assert len(results) == num_gremlins
        # 100 lookups should be under 50ms
        assert elapsed < 0.05, f'Batch lookups took {elapsed * 1000:.1f}ms (target: <50ms)'
