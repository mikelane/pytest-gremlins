"""Integration tests for incremental cache with plugin.

These tests verify that the cache integrates correctly with the mutation
testing workflow, providing cached results for unchanged code.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def pytester_with_conftest(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance with conftest that registers small marker for nested tests.

    The pytest-test-categories plugin requires tests to have size markers.
    We create a conftest.py that registers the marker and applies it by default.
    The hook uses tryfirst=True to ensure markers are applied BEFORE pytest-test-categories
    inspects them.
    """
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    # Apply small marker to all tests that don't have a size marker
    # Must run BEFORE pytest-test-categories checks for markers
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
"""
    )
    return pytester


@pytest.mark.medium
class TestCacheIntegration:
    """Tests for cache integration with the mutation testing plugin."""

    def test_first_run_populates_cache(self, pytester_with_conftest: pytest.Pytester) -> None:
        """First run stores results in cache."""
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

        # First run with cache enabled
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Cache directory should be created
        cache_dir = pytester_with_conftest.path / '.gremlins_cache'
        assert cache_dir.exists()
        assert (cache_dir / 'results.db').exists()

    def test_second_run_uses_cache(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Second run on unchanged code uses cached results."""
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

        # First run
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Second run should be faster (uses cache)
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache hits in output
        result.stdout.fnmatch_lines(['*cache hit*'])

    def test_source_change_invalidates_cache(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Modifying source file invalidates cache entries."""
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

        # First run
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify source
        pytester_with_conftest.makepyfile(
            src_module="""
            def add(a, b):
                return a + b + 0  # Modified
            """
        )

        # Second run should re-test (cache invalidated)
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        # Should show cache miss due to source change
        result.stdout.fnmatch_lines(['*cache miss*'])

    def test_test_change_invalidates_cache(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Modifying test file invalidates cache entries."""
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

        # First run
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Modify test
        pytester_with_conftest.makepyfile(
            test_module="""
            from src_module import add

            def test_add():
                assert add(1, 2) == 3
                assert add(0, 0) == 0  # Added assertion
            """
        )

        # Second run should re-test (cache invalidated)
        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(['*cache miss*'])

    def test_cache_disabled_by_default(self, pytester_with_conftest: pytest.Pytester) -> None:
        """Cache is not used when --gremlin-cache not specified."""
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

        # Run without --gremlin-cache
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py')

        # Cache directory should not be created
        cache_dir = pytester_with_conftest.path / '.gremlins_cache'
        assert not cache_dir.exists()

    def test_clear_cache_option(self, pytester_with_conftest: pytest.Pytester) -> None:
        """--gremlin-clear-cache removes all cached results."""
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

        # First run to populate cache
        pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')

        # Clear cache
        result = pytester_with_conftest.runpytest(
            '--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache', '--gremlin-clear-cache'
        )

        result.assert_outcomes(passed=1)
        # Should show cache cleared
        result.stdout.fnmatch_lines(['*cache cleared*'])
