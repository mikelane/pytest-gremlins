"""Integration performance tests for incremental cache.

These tests verify that the cache provides actual speedup in real usage,
not just correct behavior.
"""

from __future__ import annotations

import time

import pytest


@pytest.mark.medium
class DescribeCachePerformanceIntegration:
    """Integration tests verifying cache provides speedup."""

    def it_completes_faster_on_warm_run_than_cold_run(self, pytester_with_markers: pytest.Pytester) -> None:
        """Warm run (cache populated) is faster than cold run.

        This is the key acceptance test - if warm run is not faster than
        cold run, the cache is not providing value.
        """
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b

            def subtract(a, b):
                return a - b

            def multiply(a, b):
                return a * b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add, subtract, multiply

            def test_add():
                assert add(1, 2) == 3

            def test_subtract():
                assert subtract(5, 3) == 2

            def test_multiply():
                assert multiply(3, 4) == 12
            """,
        )

        # Cold run (no cache)
        cold_start = time.perf_counter()
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        cold_time = time.perf_counter() - cold_start

        # Warm run (cache populated)
        warm_start = time.perf_counter()
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        warm_time = time.perf_counter() - warm_start

        result.assert_outcomes(passed=3)

        # Warm run should be faster (cache hits skip test execution)
        # Allow for small overhead, but warm MUST be faster
        assert warm_time < cold_time, (
            f'Warm run ({warm_time:.2f}s) was NOT faster than cold run ({cold_time:.2f}s). '
            'Cache is adding overhead instead of providing speedup!'
        )

    def it_skips_test_execution_on_cache_hit(self, pytester_with_markers: pytest.Pytester) -> None:
        """Cache hits skip actual test execution, saving subprocess overhead."""
        pytester_with_markers.makepyfile(
            src_module="""
            def slow_function():
                return 42
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            import time
            from src_module import slow_function

            def test_slow():
                # This test takes 0.1s to run
                time.sleep(0.1)
                assert slow_function() == 42
            """,
        )

        # Cold run populates the cache
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Warm run should hit the cache and skip test execution
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)

        # Behavioral assertion: cache hit was reported in output, proving test execution
        # was skipped on the warm run. This is the actual contract — not wall-clock time,
        # which is dominated by subprocess startup overhead (~1.5s) regardless of cache.
        result.stdout.fnmatch_lines(['*cache hit*'])
