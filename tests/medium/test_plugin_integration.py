"""Integration tests for the pytest-gremlins plugin.

These tests verify the end-to-end plugin behavior using pytester.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def pytester_isolated(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance that disables interfering plugins.

    The pytest-test-categories plugin raises an INTERNALERROR when tests don't have
    size markers. We disable interfering plugins for nested pytester runs by creating
    a conftest.py that blocks them early.
    """
    # Create a conftest.py that disables the test-categories plugin via pytest_configure
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    # Unregister any test-categories plugin by iterating all registered plugins
    pm = config.pluginmanager
    plugins_to_remove = []

    # Iterate through all registered plugins and find test-categories related ones
    for plugin in pm.get_plugins():
        name = pm.get_name(plugin) or ''
        module_name = getattr(plugin, '__name__', '') or ''
        module_file = getattr(plugin, '__file__', '') or ''

        # Check if this is a test-categories plugin by various indicators
        if any('test' in s.lower() and 'categor' in s.lower()
               for s in [name, module_name, module_file, str(type(plugin))]):
            plugins_to_remove.append(plugin)

    # Unregister the found plugins
    for plugin in plugins_to_remove:
        try:
            pm.unregister(plugin)
        except Exception:
            pass
"""
    )
    return pytester


@pytest.mark.medium
class TestPluginBasicFunctionality:
    """Test basic plugin functionality."""

    def test_gremlins_flag_enables_mutation_testing(self, pytester_isolated: pytest.Pytester):
        """Verify that --gremlins flag enables mutation testing."""
        pytester_isolated.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult_true_for_21():
    assert is_adult(21) is True

def test_is_adult_false_for_10():
    assert is_adult(10) is False
"""
        )

        result = pytester_isolated.runpytest('--gremlins', '-v')
        result.assert_outcomes(passed=2)
        assert 'pytest-gremlins mutation report' in result.stdout.str()

    def test_gremlins_flag_generates_gremlins(self, pytester_isolated: pytest.Pytester):
        """Verify that gremlins are generated from source code."""
        pytester_isolated.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_isolated.runpytest('--gremlins', '--gremlin-targets=target_module.py', '-v')
        result.assert_outcomes(passed=1)
        # Should have generated gremlins
        output = result.stdout.str()
        assert 'Zapped:' in output or 'Survived:' in output

    def test_mutation_score_displayed(self, pytester_isolated: pytest.Pytester):
        """Verify that mutation score is displayed at the end."""
        pytester_isolated.makepyfile(
            target_module="""
def add(x, y):
    return x + y
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import add

def test_add():
    assert add(2, 3) == 5
"""
        )

        result = pytester_isolated.runpytest('--gremlins', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert '%' in output  # Mutation score percentage


@pytest.mark.medium
class TestPluginWithoutGremlinsFlag:
    """Test plugin behavior when --gremlins is not used."""

    def test_no_mutation_testing_without_flag(self, pytester_isolated: pytest.Pytester):
        """Verify that tests run normally without --gremlins flag."""
        pytester_isolated.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_isolated.runpytest('-v')
        result.assert_outcomes(passed=1)
        # Should not have mutation report
        assert 'pytest-gremlins mutation report' not in result.stdout.str()


@pytest.mark.medium
class TestPluginOperatorSelection:
    """Test operator selection via command line."""

    def test_specific_operators_via_command_line(self, pytester_isolated: pytest.Pytester):
        """Verify that specific operators can be selected."""
        pytester_isolated.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_isolated.runpytest('--gremlins', '--gremlin-operators=comparison', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert 'pytest-gremlins mutation report' in output


@pytest.mark.medium
class TestPluginReportFormats:
    """Test different report format options."""

    def test_console_report_default(self, pytester_isolated: pytest.Pytester):
        """Verify console report is generated by default."""
        pytester_isolated.makepyfile(
            target_module="""
def is_adult(age):
    return age >= 18
"""
        )
        pytester_isolated.makepyfile(
            test_target="""
from target_module import is_adult

def test_is_adult():
    assert is_adult(21) is True
"""
        )

        result = pytester_isolated.runpytest('--gremlins', '--gremlin-targets=target_module.py', '-v')
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert 'pytest-gremlins mutation report' in output
        assert 'Zapped:' in output or 'Survived:' in output
