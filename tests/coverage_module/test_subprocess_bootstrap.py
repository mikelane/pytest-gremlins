"""Tests for subprocess_bootstrap - self-bootstrapping context plugin for coverage subprocesses.

The module grabs Coverage.current() during pytest_sessionstart and registers
context-switching hooks so the coverage subprocess records full node IDs
instead of bare function names.
"""

from __future__ import annotations

from unittest.mock import (
    MagicMock,
    patch,
)

import coverage
import pytest

from pytest_gremlins.coverage.subprocess_bootstrap import (
    _strip_nodeid_markers,
    _SubprocessContextPlugin,
    pytest_sessionstart,
)


@pytest.mark.small
class DescribeStripNodeidMarkers:
    """Tests for _strip_nodeid_markers."""

    def it_strips_test_category_marker(self) -> None:
        assert _strip_nodeid_markers('test_module.py::test_add [SMALL]') == 'test_module.py::test_add'

    def it_strips_medium_marker(self) -> None:
        assert _strip_nodeid_markers('test_module.py::test_add [MEDIUM]') == 'test_module.py::test_add'

    def it_leaves_plain_nodeid_unchanged(self) -> None:
        assert _strip_nodeid_markers('test_module.py::test_add') == 'test_module.py::test_add'

    def it_leaves_parametrized_nodeid_unchanged(self) -> None:
        assert _strip_nodeid_markers('test_module.py::test_add[param1]') == 'test_module.py::test_add[param1]'


@pytest.mark.small
class DescribeSubprocessContextPluginInit:
    """Tests for _SubprocessContextPlugin.__init__."""

    def it_stores_coverage_instance(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        plugin = _SubprocessContextPlugin(mock_cov)
        assert plugin.cov is mock_cov


@pytest.mark.small
class DescribeSubprocessContextPluginSetup:
    """Tests for pytest_runtest_setup hookwrapper."""

    def it_switches_context_to_setup_phase(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov._started = True
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_setup(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|setup')

    def it_strips_marker_from_nodeid(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov._started = True
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar [SMALL]'

        list(plugin.pytest_runtest_setup(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|setup')

    def it_skips_switch_context_when_started_attr_missing(self) -> None:
        """switch_context is NOT called when cov has no _started attribute.

        Exercises the getattr default path -- if a future coverage.py
        release removes _started, the guard silently skips the call.
        """
        mock_cov = MagicMock()  # guard test: needs bare mock for del _started; bare-mock: ok
        del mock_cov._started
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_setup(mock_item))

        mock_cov.switch_context.assert_not_called()

    def it_skips_switch_context_when_coverage_is_stopped(self) -> None:
        """switch_context is NOT called when coverage._started is False."""
        mock_cov = MagicMock()  # guard test: needs bare mock with explicit _started; bare-mock: ok
        mock_cov._started = False
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_setup(mock_item))

        mock_cov.switch_context.assert_not_called()


@pytest.mark.small
class DescribeSubprocessContextPluginCall:
    """Tests for pytest_runtest_call hookwrapper."""

    def it_switches_context_to_run_phase(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov._started = True
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_call(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|run')

    def it_skips_switch_context_when_coverage_is_stopped(self) -> None:
        """switch_context is NOT called when coverage._started is False."""
        mock_cov = MagicMock()  # guard test: needs bare mock with explicit _started; bare-mock: ok
        mock_cov._started = False
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_call(mock_item))

        mock_cov.switch_context.assert_not_called()


@pytest.mark.small
class DescribeSubprocessContextPluginTeardown:
    """Tests for pytest_runtest_teardown hookwrapper."""

    def it_switches_context_to_teardown_phase(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov._started = True
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_teardown(mock_item))

        mock_cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|teardown')

    def it_skips_switch_context_when_coverage_is_stopped(self) -> None:
        """switch_context is NOT called when coverage._started is False."""
        mock_cov = MagicMock()  # guard test: needs bare mock with explicit _started; bare-mock: ok
        mock_cov._started = False
        plugin = _SubprocessContextPlugin(mock_cov)
        mock_item = MagicMock(spec=pytest.Item)
        mock_item.nodeid = 'tests/test_foo.py::test_bar'

        list(plugin.pytest_runtest_teardown(mock_item))

        mock_cov.switch_context.assert_not_called()


@pytest.mark.small
class DescribePytestSessionstart:
    """Tests for the module-level pytest_sessionstart hook."""

    def it_registers_plugin_when_coverage_is_running(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_session = MagicMock(spec=pytest.Session)

        with patch('pytest_gremlins.coverage.subprocess_bootstrap.coverage') as mock_coverage:
            mock_coverage.Coverage.current.return_value = mock_cov
            pytest_sessionstart(mock_session)

        mock_session.config.pluginmanager.register.assert_called_once()
        registered_plugin = mock_session.config.pluginmanager.register.call_args[0][0]
        assert isinstance(registered_plugin, _SubprocessContextPlugin)
        assert registered_plugin.cov is mock_cov

    def it_skips_registration_when_no_coverage_instance(self) -> None:
        mock_session = MagicMock(spec=pytest.Session)

        with patch('pytest_gremlins.coverage.subprocess_bootstrap.coverage') as mock_coverage:
            mock_coverage.Coverage.current.return_value = None
            pytest_sessionstart(mock_session)

        mock_session.config.pluginmanager.register.assert_not_called()

    def it_registers_with_named_plugin_id(self) -> None:
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_session = MagicMock(spec=pytest.Session)

        with patch('pytest_gremlins.coverage.subprocess_bootstrap.coverage') as mock_coverage:
            mock_coverage.Coverage.current.return_value = mock_cov
            pytest_sessionstart(mock_session)

        call_kwargs = mock_session.config.pluginmanager.register.call_args[1]
        assert call_kwargs['name'] == 'gremlin-subprocess-context'
