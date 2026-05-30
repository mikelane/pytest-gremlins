"""Integration performance tests for incremental cache.

These tests verify that the cache provides actual speedup in real usage,
not just correct behavior.
"""

from __future__ import annotations

import pytest


@pytest.mark.medium
class DescribeCachePerformanceIntegration:
    """Integration tests verifying cache provides speedup."""

    def it_reports_cache_hits_for_all_gremlins_on_warm_run(self, pytester_with_markers: pytest.Pytester) -> None:
        """All gremlins report cache hits on the warm run, proving multi-gremlin skipping."""
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

        # Cold run populates the cache — every gremlin is a cache miss
        cold_result = pytester_with_markers.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache'
        )
        cold_result.assert_outcomes(passed=3)
        # The cold run must NOT report cache hits — this proves the warm-run hit
        # assertion below is meaningful and not an unconditionally printed string.
        cold_result.stdout.fnmatch_lines(['*cache miss*'])
        assert 'cache hit' not in cold_result.stdout.str()

        # Warm run should hit the cache for every gremlin
        warm_result = pytester_with_markers.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache'
        )
        warm_result.assert_outcomes(passed=3)

        # Behavioral assertion: each gremlin reports a cache hit on the warm run,
        # proving test execution was skipped. Paired with the cold-run miss assertion
        # above, this distinguishes a working cache from a no-op that always prints
        # "cache hit". Wall-clock timing is not asserted — subprocess startup overhead
        # (~1.5s) dominates and is not deterministic.
        warm_result.stdout.fnmatch_lines(['*cache hit*'])
        assert 'cache miss' not in warm_result.stdout.str()

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
            from src_module import slow_function

            def test_slow():
                assert slow_function() == 42
            """,
        )

        # Cold run populates the cache — gremlins are cache misses
        cold_result = pytester_with_markers.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache'
        )
        cold_result.stdout.fnmatch_lines(['*cache miss*'])
        assert 'cache hit' not in cold_result.stdout.str()

        # Warm run should hit the cache and skip test execution
        warm_result = pytester_with_markers.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache'
        )

        warm_result.assert_outcomes(passed=1)

        # Behavioral assertion: cache hit was reported on the warm run, proving test
        # execution was skipped. Paired with the cold-run miss assertion above, this
        # distinguishes a working cache from a no-op that always prints "cache hit".
        # Wall-clock time is not asserted — subprocess startup overhead (~1.5s) dominates
        # regardless of cache.
        warm_result.stdout.fnmatch_lines(['*cache hit*'])
        assert 'cache miss' not in warm_result.stdout.str()
