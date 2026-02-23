"""Integration tests for incremental cache with plugin.

These tests verify that the cache integrates correctly with the mutation
testing workflow, providing cached results for unchanged code.
"""

from __future__ import annotations

import pytest


@pytest.mark.medium
class DescribeCacheIntegration:
    """Tests for cache integration with the mutation testing plugin."""

    def it_first_run_populates_cache(self, pytester_with_markers: pytest.Pytester) -> None:
        """First run stores results in cache."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # First run with cache enabled
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Cache directory should be created
        cache_dir = pytester_with_markers.path / '.gremlins_cache'
        assert cache_dir.exists()
        assert (cache_dir / 'results.db').exists()

    def it_second_run_uses_cache(self, pytester_with_markers: pytest.Pytester) -> None:
        """Second run on unchanged code uses cached results."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # First run
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Second run should be faster (uses cache)
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache hits in output
        result.stdout.fnmatch_lines(['*cache hit*'])

    def it_invalidates_cache_when_source_file_changes(self, pytester_with_markers: pytest.Pytester) -> None:
        """Modifying source file invalidates cache entries."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # First run
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify source
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b + 0  # Modified
            """,
        )

        # Second run should re-test (cache invalidated)
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache miss due to source change
        result.stdout.fnmatch_lines(['*cache miss*'])

    def it_invalidates_cache_when_test_file_is_modified(self, pytester_with_markers: pytest.Pytester) -> None:
        """Modifying test file invalidates cache entries."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # First run
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify test
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
                assert add(0, 0) == 0  # Added assertion
            """,
        )

        # Second run should re-test (cache invalidated)
        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(['*cache miss*'])

    def it_cache_disabled_by_default(self, pytester_with_markers: pytest.Pytester) -> None:
        """Cache is not used when --gremlin-cache not specified."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # Run without --gremlin-cache
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py')

        # Cache directory should not be created
        cache_dir = pytester_with_markers.path / '.gremlins_cache'
        assert not cache_dir.exists()

    def it_clears_all_cached_results_when_gremlin_clear_cache_is_set(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        """--gremlin-clear-cache removes all cached results."""
        pytester_with_markers.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """,
        )
        pytester_with_markers.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """,
        )

        # First run to populate cache
        pytester_with_markers.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Clear cache
        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--gremlin-cache',
            '--gremlin-clear-cache',
        )

        result.assert_outcomes(passed=1)
        # Should show cache cleared
        result.stdout.fnmatch_lines(['*cache cleared*'])
