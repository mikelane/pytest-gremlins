"""Tests for GremlinContextPlugin - per-test coverage context switching.

The plugin is a pytest hookwrapper that calls cov.switch_context() before each
test phase so that coverage data is tagged with the test that exercised each line.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin


@pytest.mark.small
class TestGremlinContextPluginInit:
    """Tests for GremlinContextPlugin.__init__."""

    def test_stores_coverage_instance(self) -> None:
        """The cov attribute is the instance passed to __init__."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        assert plugin.cov is mock_cov


@pytest.mark.small
class TestGremlinContextPluginSetup:
    """Tests for pytest_runtest_setup hookwrapper."""

    def test_switches_context_to_setup_phase(self) -> None:
        """switch_context is called with '{nodeid}|setup' before yielding."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        mock_item = MagicMock()
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_setup(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|setup')

    def test_yields_control_to_next_hook(self) -> None:
        """The generator yields exactly once (hookwrapper contract)."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        mock_item = MagicMock()
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        gen = plugin.pytest_runtest_setup(mock_item)
        next(gen)  # pre-yield: switch_context called
        with pytest.raises(StopIteration):
            next(gen)  # post-yield: generator exhausted


@pytest.mark.small
class TestGremlinContextPluginCall:
    """Tests for pytest_runtest_call hookwrapper."""

    def test_switches_context_to_run_phase(self) -> None:
        """switch_context is called with '{nodeid}|run' before yielding."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        mock_item = MagicMock()
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_call(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|run')

    def test_nodeid_with_class_uses_full_nodeid(self) -> None:
        """Full nodeid including class name is passed to switch_context."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        mock_item = MagicMock()
        mock_item.nodeid = 'tests/test_foo.py::TestClass::test_bar'

        list(plugin.pytest_runtest_call(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::TestClass::test_bar|run')


@pytest.mark.small
class TestGremlinContextPluginTeardown:
    """Tests for pytest_runtest_teardown hookwrapper."""

    def test_switches_context_to_teardown_phase(self) -> None:
        """switch_context is called with '{nodeid}|teardown' before yielding."""
        mock_cov = MagicMock()
        plugin = GremlinContextPlugin(mock_cov)
        mock_item = MagicMock()
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_teardown(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|teardown')
