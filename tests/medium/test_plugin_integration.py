"""Integration tests for the pytest-gremlins plugin.

These tests verify the end-to-end plugin behavior using pytester.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def pytester_with_conftest(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance with conftest that registers small marker for nested tests.

    The pytest-test-categories plugin requires tests to have size markers.
    We create a conftest.py that registers the marker and applies it by default.
    """
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

def pytest_collection_modifyitems(items):
    # Apply small marker to all tests that don't have a size marker
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
"""
    )
    return pytester


@pytest.mark.medium
class TestPluginBasicFunctionality:
    """Test basic plugin functionality."""

    def test_gremlins_flag_enables_mutation_testing(self, pytester_with_conftest: pytest.Pytester):
        """Verify that --gremlins flag enables mutation testing."""
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult_true_for_21():
    assert is_adult(21) is True

def test_is_adult_false_for_10():
    assert is_adult(10) is False
"""
        )

        result = pytester_with_conftest.runpytest('--gremlins', '-v')
        result.assert_outcomes(passed=2)
        assert 'pytest-gremlins mutation report' in result.stdout.str()

    def test_gremlins_flag_generates_gremlins(self, pytester_with_conftest: pytest.Pytester):
        """Verify that gremlins are generated from source code."""
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=target_module.py', '-v')
        result.assert_outcomes(passed=1)
        # Should have generated gremlins
        output = result.stdout.str()
        assert 'Zapped:' in output or 'Survived:' in output

    def test_mutation_score_displayed(self, pytester_with_conftest: pytest.Pytester):
        """Verify that mutation score is displayed at the end."""
        pytester_with_conftest.makepyfile(
            target_module="""
def add(x, y):
    return x + y
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import add

def test_add():
    assert add(2, 3) == 5
"""
        )

        result = pytester_with_conftest.runpytest('--gremlins', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert '%' in output  # Mutation score percentage


@pytest.mark.medium
class TestPluginWithoutGremlinsFlag:
    """Test plugin behavior when --gremlins is not used."""

    def test_no_mutation_testing_without_flag(self, pytester_with_conftest: pytest.Pytester):
        """Verify that tests run normally without --gremlins flag."""
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_with_conftest.runpytest('-v')
        result.assert_outcomes(passed=1)
        # Should not have mutation report
        assert 'pytest-gremlins mutation report' not in result.stdout.str()


@pytest.mark.medium
class TestPluginOperatorSelection:
    """Test operator selection via command line."""

    def test_specific_operators_via_command_line(self, pytester_with_conftest: pytest.Pytester):
        """Verify that specific operators can be selected."""
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-operators=comparison', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert 'pytest-gremlins mutation report' in output


@pytest.mark.medium
class TestPluginReportFormats:
    """Test different report format options."""

    def test_console_report_default(self, pytester_with_conftest: pytest.Pytester):
        """Verify console report is generated by default."""
        pytester_with_conftest.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_with_conftest.runpytest('--gremlins', '--gremlin-targets=target_module.py', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert 'pytest-gremlins mutation report' in output
        assert 'Zapped:' in output or 'Survived:' in output
