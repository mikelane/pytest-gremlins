"""Tests measuring actual cache overhead in plugin usage pattern.

These tests identify why the cache makes things slower instead of faster.
"""

from pathlib import Path
import time

import pytest

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore


@pytest.mark.small
class TestUpfrontHashingOverhead:
    """Tests for upfront file hashing overhead."""

    def test_upfront_hashing_cost_for_typical_project(self, tmp_path: Path) -> None:
        """Measure upfront hashing cost for a typical project.

        Simulates the current plugin behavior where ALL source and test
        files are hashed upfront during pytest_collection_finish.
        """
        # Create simulated project structure
        src_dir = tmp_path / 'src'
        test_dir = tmp_path / 'tests'
        src_dir.mkdir()
        test_dir.mkdir()

        # 20 source files, ~100 lines each
        for i in range(20):
            content = '\n'.join([f'def func_{j}(): return {j}' for j in range(100)])
            (src_dir / f'module_{i}.py').write_text(content)

        # 30 test files, ~50 lines each
        for i in range(30):
            content = '\n'.join([f'def test_{j}(): assert True' for j in range(50)])
            (test_dir / f'test_{i}.py').write_text(content)

        hasher = ContentHasher()

        # Measure upfront hashing cost (current plugin behavior)
        start = time.perf_counter()
        source_hashes = {}
        for f in src_dir.iterdir():
            source_hashes[str(f)] = hasher.hash_file(f)
        test_hashes = {}
        for f in test_dir.iterdir():
            test_hashes[str(f)] = hasher.hash_file(f)
        upfront_time = time.perf_counter() - start

        # This happens on EVERY run, even when cache hit rate is 100%
        # For 50 files, this should be under 50ms
        assert upfront_time < 0.05, (
            f'Upfront hashing took {upfront_time * 1000:.1f}ms for 50 files. '
            'This overhead occurs on every run regardless of cache hits.'
        )


@pytest.mark.small
class TestSqliteCommitOverhead:
    """Tests for SQLite commit overhead."""

    def test_individual_commits_are_slow(self, tmp_path: Path) -> None:
        """Individual commits per write are slower than batch commits."""
        db_path = tmp_path / 'results.db'

        # Current behavior: commit after each write
        with ResultStore(db_path) as store:
            start = time.perf_counter()
            for i in range(100):
                store.put(f'key_{i}', {'status': 'zapped', 'test': f'test_{i}'})
            individual_time = time.perf_counter() - start

        # This should be under 500ms for 100 entries
        # If it's slow, the per-commit overhead is the culprit
        assert individual_time < 0.5, (
            f'Individual commits took {individual_time * 1000:.1f}ms for 100 entries. '
            'SQLite commits are expensive - should batch them.'
        )


@pytest.mark.small
class TestCacheKeyComputationOverhead:
    """Tests for cache key computation overhead."""

    def test_repeated_hash_combined_calls(self, tmp_path: Path) -> None:
        """Measure overhead of computing combined test hashes repeatedly.

        For each gremlin, we call hash_combined with the test hashes.
        With 100 gremlins and 10 tests each, that's 100 hash operations.
        """
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100
        num_tests = 10

        # Pre-compute test hashes (simulating upfront hashing)
        test_hashes = {f'test_{i}': f'hash_{i}' * 10 for i in range(num_tests)}

        with IncrementalCache(cache_dir) as cache:
            # Measure time to build 100 cache keys
            start = time.perf_counter()
            for i in range(num_gremlins):
                cache._build_cache_key(f'gremlin_{i}', 'source_hash', test_hashes)
            key_time = time.perf_counter() - start

        # 100 key computations should be under 10ms
        assert key_time < 0.01, (
            f'Cache key computation took {key_time * 1000:.1f}ms for {num_gremlins} gremlins. '
            'This happens for both cache reads AND writes.'
        )


@pytest.mark.small
class TestTotalCacheOverhead:
    """Tests measuring total cache overhead vs no-cache baseline."""

    def test_cache_overhead_should_not_exceed_benefit(self, tmp_path: Path) -> None:
        """Total cache overhead must be less than time saved.

        For cache to be beneficial:
        - Cache overhead < (num_hits * avg_test_time)

        If we have 100 gremlins with 100% cache hits, and tests take 1s each:
        - Time without cache: 100 * 1s = 100s
        - Time with cache (hits): 100 * overhead
        - Cache overhead MUST be << 1s per gremlin for this to be worthwhile

        Current problem: Cache overhead per gremlin is too high.
        """
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100
        num_tests = 5

        hasher = ContentHasher()
        source_hash = hasher.hash_string('def add(a, b): return a + b')
        test_hashes = {f'test_{i}': hasher.hash_string(f'def test_{i}(): pass') for i in range(num_tests)}

        # COLD RUN: Populate cache
        with IncrementalCache(cache_dir) as cache:
            for i in range(num_gremlins):
                cache.cache_result(
                    f'gremlin_{i}',
                    source_hash,
                    test_hashes,
                    {'status': 'zapped', 'killing_test': 'test_0'},
                )

        # WARM RUN: Measure cache hit overhead
        with IncrementalCache(cache_dir) as cache:
            start = time.perf_counter()
            hits = 0
            for i in range(num_gremlins):
                result = cache.get_cached_result(f'gremlin_{i}', source_hash, test_hashes)
                if result:
                    hits += 1
            warm_time = time.perf_counter() - start

        assert hits == num_gremlins, f'Expected {num_gremlins} hits, got {hits}'

        per_gremlin_overhead_ms = (warm_time / num_gremlins) * 1000

        # Target: < 0.5ms per gremlin for cache lookup
        # At 0.5ms per gremlin * 100 gremlins = 50ms total overhead
        # This is acceptable if test execution saves > 50ms
        assert per_gremlin_overhead_ms < 0.5, (
            f'Cache overhead per gremlin: {per_gremlin_overhead_ms:.3f}ms '
            f'(total: {warm_time * 1000:.1f}ms for {num_gremlins} gremlins). '
            'Target: < 0.5ms per gremlin.'
        )


@pytest.mark.small
class TestCacheWithBatchOperations:
    """Tests demonstrating potential for batch optimization."""

    def test_batch_get_potential(self, tmp_path: Path) -> None:
        """Batch get could retrieve all cached results in one query.

        Current: N SQLite queries for N gremlins
        Better: 1 SQLite query with WHERE cache_key IN (...)
        """
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100

        hasher = ContentHasher()
        source_hash = hasher.hash_string('content')
        test_hashes = {'test': hasher.hash_string('test')}

        # Populate cache
        with IncrementalCache(cache_dir) as cache:
            for i in range(num_gremlins):
                cache.cache_result(f'g_{i}', source_hash, test_hashes, {'status': 'zapped'})

        # Measure individual gets (current behavior)
        with IncrementalCache(cache_dir) as cache:
            start = time.perf_counter()
            for i in range(num_gremlins):
                cache.get_cached_result(f'g_{i}', source_hash, test_hashes)
            individual_time = time.perf_counter() - start

        # Total time should be < 50ms for 100 lookups (0.5ms each)
        assert individual_time < 0.05, (
            f'Individual lookups took {individual_time * 1000:.1f}ms for {num_gremlins} entries. '
            'Could be faster with batch queries.'
        )
