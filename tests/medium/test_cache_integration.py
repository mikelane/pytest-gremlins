"""Integration tests for incremental cache with plugin.

These tests verify that the cache integrates correctly with the mutation
testing workflow, providing cached results for unchanged code.
"""

import pytest


@pytest.mark.medium
class TestCacheIntegration:
    """Tests for cache integration with the mutation testing plugin."""

    def test_first_run_populates_cache(self, pytester):
        """First run stores results in cache."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # First run with cache enabled
        result = pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Cache directory should be created
        cache_dir = pytester.path / '.gremlins_cache'
        assert cache_dir.exists()
        assert (cache_dir / 'results.db').exists()

    def test_second_run_uses_cache(self, pytester):
        """Second run on unchanged code uses cached results."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # First run
        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Second run should be faster (uses cache)
        result = pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache hits in output
        result.stdout.fnmatch_lines(['*cache hit*'])

    def test_source_change_invalidates_cache(self, pytester):
        """Modifying source file invalidates cache entries."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # First run
        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify source
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b + 0  # Modified
            """
        )

        # Second run should re-test (cache invalidated)
        result = pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache miss due to source change
        result.stdout.fnmatch_lines(['*cache miss*'])

    def test_test_change_invalidates_cache(self, pytester):
        """Modifying test file invalidates cache entries."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # First run
        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify test
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
                assert add(0, 0) == 0  # Added assertion
            """
        )

        # Second run should re-test (cache invalidated)
        result = pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(['*cache miss*'])

    def test_cache_disabled_by_default(self, pytester):
        """Cache is not used when --gremlin-cache not specified."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # Run without --gremlin-cache
        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py')

        # Cache directory should not be created
        cache_dir = pytester.path / '.gremlins_cache'
        assert not cache_dir.exists()

    def test_clear_cache_option(self, pytester):
        """--gremlin-clear-cache removes all cached results."""
        pytester.makepyfile(
            src_module="""
            def add(a, b):
                return a + b
            """
        )
        pytester.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
            """
        )

        # First run to populate cache
        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Clear cache
        result = pytester.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache', '--gremlin-clear-cache'
        )

        result.assert_outcomes(passed=1)
        # Should show cache cleared
        result.stdout.fnmatch_lines(['*cache cleared*'])
