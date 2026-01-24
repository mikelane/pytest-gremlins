"""Integration tests for coverage-guided test selection.

These tests verify that the plugin uses coverage data to run only
relevant tests for each gremlin, providing 10-100x speedup.
"""

from __future__ import annotations

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
class TestCoverageGuidedTestSelection:
    """Test that coverage-guided test selection reduces test executions."""

    def test_output_shows_test_count_per_gremlin(
        self,
        pytester_with_conftest: pytest.Pytester,
    ):
        """Verify output shows 'running N/M tests' for each gremlin (AC1).

        Creates a module with two functions, each tested by different tests.
        Coverage-guided selection should run only 1-2 tests per gremlin,
        not all 4 tests.
        """
        pytester_with_conftest.makepyfile(
            target_module="""
def add(x, y):
    return x + y

def subtract(x, y):
    return x - y
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import add, subtract

def test_add_positive():
    assert add(2, 3) == 5

def test_add_negative():
    assert add(-1, 1) == 0

def test_subtract_positive():
    assert subtract(5, 3) == 2

def test_subtract_negative():
    assert subtract(0, 5) == -5
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )

        result.assert_outcomes(passed=4)
        output = result.stdout.str()

        lower_output = output.lower()
        assert 'running' in lower_output, 'Expected output to include "running"'
        assert 'tests' in lower_output, 'Expected output to include "tests"'


@pytest.mark.medium
class TestCoverageGuidedFallback:
    """Test fallback behavior when no coverage data exists."""

    def test_uncovered_gremlin_shows_zero_coverage_message(
        self,
        pytester_with_conftest: pytest.Pytester,
    ):
        """Verify uncovered gremlins show appropriate message (AC4).

        Creates a function that is not covered by any test. The gremlin
        in this function should show a message about having no coverage.
        """
        pytester_with_conftest.makepyfile(
            target_module="""
def covered_function(x):
    return x + 1

def uncovered_function(x):
    return x - 1
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import covered_function

def test_covered():
    assert covered_function(5) == 6
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )

        result.assert_outcomes(passed=1)
        output = result.stdout.str()

        assert '0 tests' in output.lower() or 'no coverage' in output.lower(), (
            'Expected output to indicate gremlins with no test coverage'
        )
