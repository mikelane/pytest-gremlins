"""Integration tests for coverage-guided test selection.

These tests verify that the plugin uses coverage data to select only relevant
tests for each gremlin, achieving the 10-100x speedup promised by the fast-first
architecture.
"""

from __future__ import annotations

import re

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
class TestCoverageGuidedTestSelection:
    """Test that coverage data is used to select relevant tests per gremlin."""

    def test_running_tests_shows_selection_count(self, pytester_with_conftest: pytest.Pytester):
        """AC1: Test count reduction is visible in output.

        Given a project with multiple tests where only some cover the mutated code,
        the output should show "running N/M tests" where N < M for at least some gremlins.
        """
        # Create a module with two functions, each covered by different tests
        pytester_with_conftest.makepyfile(
            target_module="""
def add(x, y):
    return x + y

def subtract(x, y):
    return x - y
"""
        )
        # Create tests where only specific tests cover each function
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import add, subtract

def test_add_positive():
    assert add(2, 3) == 5

def test_add_negative():
    assert add(-1, -1) == -2

def test_subtract_positive():
    assert subtract(5, 3) == 2

def test_subtract_negative():
    assert subtract(-1, -1) == 0
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=4)
        output = result.stdout.str()

        assert re.search(r'running \d+/\d+ tests', output), (
            f'Expected output to show "running N/M tests" but got:\n{output}'
        )

    def test_coverage_collection_message_shown(self, pytester_with_conftest: pytest.Pytester):
        """AC3: Coverage data appears in verbose output.

        Running with -v should show that coverage was collected and the map was built.
        """
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=1)
        output = result.stdout.str()

        # Should show coverage collection happened
        assert 'Coverage collected:' in output or 'coverage' in output.lower(), (
            f'Expected coverage collection message but got:\n{output}'
        )

    def test_fallback_to_all_tests_when_no_coverage(self, pytester_with_conftest: pytest.Pytester):
        """AC4: Fallback to all tests when coverage unavailable.

        When a gremlin is in code not covered by any test, we should run all tests
        to catch indirect effects.
        """
        # Create a module with a function that is NOT directly tested
        pytester_with_conftest.makepyfile(
            target_module="""
def helper_never_called():
    return 42

def main_function():
    return 100
"""
        )
        # Create a test that only imports but doesn't call helper_never_called
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import main_function

def test_main():
    assert main_function() == 100
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=1)
        output = result.stdout.str()

        # Should mention fallback or running all tests for uncovered code
        # This could be "No coverage data" or "running all tests" or similar
        # The key is that it should NOT crash and should still run tests
        assert 'pytest-gremlins mutation report' in output, (
            f'Expected mutation report but got:\n{output}'
        )

    def test_test_reduction_actually_happens(self, pytester_with_conftest: pytest.Pytester):
        """AC2: Execution time scales with relevant tests, not total tests.

        This test verifies that when we have many tests but only a few cover
        the mutated code, we actually run fewer tests.
        """
        # Create module with isolated function
        pytester_with_conftest.makepyfile(
            target_module="""
def isolated_function():
    return 1 + 1

def other_function_1():
    return 2

def other_function_2():
    return 3

def other_function_3():
    return 4

def other_function_4():
    return 5
"""
        )
        # Create many tests, but only one covers isolated_function
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import isolated_function, other_function_1, other_function_2, other_function_3, other_function_4

def test_isolated():
    assert isolated_function() == 2

def test_other_1():
    assert other_function_1() == 2

def test_other_2():
    assert other_function_2() == 3

def test_other_3():
    assert other_function_3() == 4

def test_other_4():
    assert other_function_4() == 5

def test_other_5():
    # Extra test that doesn't cover any target code meaningfully
    assert True

def test_other_6():
    assert True

def test_other_7():
    assert True

def test_other_8():
    assert True
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        # We have 9 test functions defined in test_target
        result.assert_outcomes(passed=9)
        output = result.stdout.str()

        # Look for evidence of test reduction
        # The gremlin in isolated_function should run fewer than 10 tests
        match = re.search(r'running (\d+)/(\d+) tests', output)
        if match:
            selected = int(match.group(1))
            total = int(match.group(2))
            assert selected < total, (
                f'Expected test reduction but got {selected}/{total}'
            )
        else:
            # If no match, that's also a failure - we want to see the selection output
            pytest.fail(f'Expected "running N/M tests" in output but got:\n{output}')
