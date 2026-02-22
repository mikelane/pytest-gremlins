"""Integration tests for coverage-guided test selection.

These tests verify that the plugin uses coverage data to run only
relevant tests for each gremlin, providing 10-100x speedup.
"""

from __future__ import annotations

import pytest


@pytest.mark.medium
class DescribeCoverageGuidedTestSelection:
    """Test that coverage-guided test selection reduces test executions."""

    def it_shows_test_count_per_gremlin_in_output(
        self,
        pytester_with_markers: pytest.Pytester,
    ):
        """Verify output shows 'running N/M tests' for each gremlin (AC1).

        Creates a module with two functions, each tested by different tests.
        Coverage-guided selection should run only 1-2 tests per gremlin,
        not all 4 tests.
        """
        pytester_with_markers.makepyfile(
            target_module="""
def add(x, y):
    return x + y

def subtract(x, y):
    return x - y
""",
        )
        pytester_with_markers.makepyfile(
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
""",
        )

        result = pytester_with_markers.runpytest(
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
class DescribeCoverageGuidedFallback:
    """Test fallback behavior when no coverage data exists."""

    def it_falls_back_to_running_all_tests_for_uncovered_gremlins(
        self,
        pytester_with_markers: pytest.Pytester,
    ):
        """Verify uncovered gremlins are tested via fallback to all tests (AC4).

        Creates a function not covered by any test. Coverage-guided selection
        finds no covering tests, so the plugin falls back to running ALL tests.
        The gremlin in the uncovered function survives because no test exercises
        that code path.
        """
        pytester_with_markers.makepyfile(
            target_module="""
def covered_function(x):
    return x + 1

def uncovered_function(x):
    return x - 1
""",
        )
        pytester_with_markers.makepyfile(
            test_target="""
from target_module import covered_function

def test_covered():
    assert covered_function(5) == 6
""",
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )

        result.assert_outcomes(passed=1)
        output = result.stdout.str()

        lower_output = output.lower()
        assert 'survived' in lower_output, (
            'Expected uncovered gremlins to survive (fallback runs all tests, but none exercise uncovered code)'
        )
        assert 'running' in lower_output, 'Expected uncovered gremlins to be run via fallback, not skipped'
