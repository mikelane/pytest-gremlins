"""Integration performance tests for incremental cache.

These tests verify that the cache provides actual speedup in real usage,
not just correct behavior.
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def pytester_with_conftest(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance with conftest that registers small marker."""
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
"""
    )
    return pytester


@pytest.mark.medium
class TestCachePerformanceIntegration:
    """Integration tests verifying cache provides speedup."""

    def test_warm_run_is_faster_than_cold_run(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Warm run (cache populated) is faster than cold run.

        This is the key acceptance test - if warm run is not faster than
        cold run, the cache is not providing value.
        """
        pytester_with_conftest.makepyfile(
            src_module="""
            def add(a, b):
                return a + b

            def subtract(a, b):
                return a - b

            def multiply(a, b):
                return a * b
            """
        )
        pytester_with_conftest.makepyfile(
            test_module="""
            from src_module import add, subtract, multiply

            def test_add():
                assert add(1, 2) == 3

            def test_subtract():
                assert subtract(5, 3) == 2

            def test_multiply():
                assert multiply(3, 4) == 12
            """
        )

        # Cold run (no cache)
        cold_start = time.perf_counter()
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        cold_time = time.perf_counter() - cold_start

        # Warm run (cache populated)
        warm_start = time.perf_counter()
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        warm_time = time.perf_counter() - warm_start

        result.assert_outcomes(passed=3)

        # Warm run should be faster (cache hits skip test execution)
        # Allow for small overhead, but warm MUST be faster
        assert warm_time < cold_time, (
            f'Warm run ({warm_time:.2f}s) was NOT faster than cold run ({cold_time:.2f}s). '
            'Cache is adding overhead instead of providing speedup!'
        )

    def test_cache_hit_skips_test_execution(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Cache hits skip actual test execution, saving subprocess overhead."""
        pytester_with_conftest.makepyfile(
            src_module="""
            def slow_function():
                return 42
            """
        )
        pytester_with_conftest.makepyfile(
            test_module="""
            import time
            from src_module import slow_function

            def test_slow():
                # This test takes 0.1s to run
                time.sleep(0.1)
                assert slow_function() == 42
            """
        )

        # Cold run (must execute slow test)
        cold_start = time.perf_counter()
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        cold_time = time.perf_counter() - cold_start

        # Warm run (should skip test execution via cache)
        warm_start = time.perf_counter()
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        warm_time = time.perf_counter() - warm_start

        result.assert_outcomes(passed=1)

        # Verify cache hit was reported
        result.stdout.fnmatch_lines(['*cache hit*'])

        # Warm run should be significantly faster (skipped 0.1s+ of test execution)
        # With multiple gremlins, this compounds
        assert warm_time < cold_time, f'Warm run ({warm_time:.2f}s) was NOT faster than cold run ({cold_time:.2f}s)'

    def test_no_cache_mode_baseline(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Establish baseline for no-cache mode."""
        pytester_with_conftest.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester_with_conftest.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # Run without cache
        no_cache_start = time.perf_counter()
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py')
        no_cache_time = time.perf_counter() - no_cache_start

        # Run with cache (cold)
        cache_cold_start = time.perf_counter()
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        cache_cold_time = time.perf_counter() - cache_cold_start

        # Run with cache (warm)
        cache_warm_start = time.perf_counter()
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        cache_warm_time = time.perf_counter() - cache_warm_start

        result.assert_outcomes(passed=1)

        # Cold cache run should not be significantly slower than no-cache
        # (Small overhead is acceptable for first run)
        cold_overhead = cache_cold_time - no_cache_time
        assert cold_overhead < 1.0, (
            f'Cold cache run has {cold_overhead:.2f}s overhead vs no-cache. '
            'Cache initialization should not add significant overhead.'
        )

        # Warm cache run should be faster than no-cache
        assert cache_warm_time < no_cache_time, (
            f'Warm cache ({cache_warm_time:.2f}s) should be faster than no-cache ({no_cache_time:.2f}s)'
        )
