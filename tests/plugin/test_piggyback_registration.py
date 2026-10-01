"""Tests for PIGGYBACK mode registration of GremlinContextPlugin.

When --cov is active (PIGGYBACK mode), pytest_sessionstart must:
1. Detect the _cov plugin
2. Register GremlinContextPlugin on the coverage instance from _cov

When --cov is absent (PRIVATE mode), no GremlinContextPlugin is registered
via the _cov path.
"""

from __future__ import annotations

from unittest.mock import (
    MagicMock,
    patch,
)

import coverage
from coverage.exceptions import CoverageException
import pytest

from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin
from pytest_gremlins.plugin import (
    CoverageMode,
    GremlinSession,
    _set_session,
    pytest_sessionstart,
)


@pytest.mark.small
class DescribeGremlinSessionCoverageMode:
    """GremlinSession stores coverage_mode field."""

    def it_defaults_to_private_coverage_mode(self) -> None:
        """GremlinSession defaults to PRIVATE mode when no mode specified."""
        gs = GremlinSession()
        assert gs.coverage_mode == CoverageMode.PRIVATE

    def it_allows_setting_coverage_mode_to_piggyback(self) -> None:
        """GremlinSession accepts PIGGYBACK mode."""
        gs = GremlinSession(coverage_mode=CoverageMode.PIGGYBACK)
        assert gs.coverage_mode == CoverageMode.PIGGYBACK

    def it_treats_piggyback_and_private_as_distinct_in_session(self) -> None:
        """PIGGYBACK and PRIVATE produce different session states."""
        gs_piggyback = GremlinSession(coverage_mode=CoverageMode.PIGGYBACK)
        gs_private = GremlinSession(coverage_mode=CoverageMode.PRIVATE)
        assert gs_piggyback.coverage_mode != gs_private.coverage_mode


@pytest.mark.small
class DescribePiggybackContextPluginRegistration:
    """pytest_sessionstart registers GremlinContextPlugin in PIGGYBACK mode."""

    def it_registers_context_plugin_when_cov_plugin_present(self) -> None:
        """When _cov plugin exists, registers GremlinContextPlugin on its coverage."""
        cov_controller = MagicMock()  # pytest-cov CovController: internal type, no public spec; bare-mock: ok
        cov_instance = MagicMock(spec=coverage.Coverage)
        cov_controller.cov = cov_instance

        cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        cov_plugin.cov_controller = cov_controller

        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        _set_session(gs)

        pytest_sessionstart(session)

        registered_plugins = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        context_plugins = [p for p in registered_plugins if isinstance(p, GremlinContextPlugin)]
        assert len(context_plugins) == 1
        assert context_plugins[0].cov is cov_instance

    @pytest.mark.parametrize('core', ['CTracer', 'PyTracer', '-none-'])
    def it_registers_context_plugin_when_the_cov_core_supports_contexts(self, core: str) -> None:
        """Cores other than sysmon honor switch_context, so the plugin is registered (#531)."""
        session = self._piggyback_session_with_core(core)

        pytest_sessionstart(session)

        registered = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        assert any(isinstance(p, GremlinContextPlugin) for p in registered)

    def it_skips_context_plugin_when_the_cov_core_is_sysmon(self) -> None:
        """sysmon drops API-driven contexts and warns; the subprocess map is used instead (#531)."""
        session = self._piggyback_session_with_core('SysMonitor')

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()

    def it_registers_context_plugin_when_sys_info_raises_a_coverage_exception(self) -> None:
        """A failing core probe is not evidence of sysmon, so the plugin is still registered (#531)."""
        session = self._piggyback_session_with_core('CTracer')
        cov_instance = session.config.pluginmanager.get_plugin.return_value.cov_controller.cov
        cov_instance.sys_info.side_effect = CoverageException('cannot determine core')

        pytest_sessionstart(session)

        registered = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        assert any(isinstance(p, GremlinContextPlugin) for p in registered)

    @pytest.mark.parametrize(
        'malformed_sys_info',
        [
            pytest.param(42, id='non-iterable'),
            pytest.param([('core',)], id='one-element-tuple'),
            pytest.param([('core', 'SysMonitor', 'extra')], id='three-element-tuple'),
        ],
    )
    def it_registers_context_plugin_when_sys_info_has_an_unexpected_shape(self, malformed_sys_info: object) -> None:
        """sys_info is a debug API; a shape change is not evidence of sysmon (#531)."""
        session = self._piggyback_session_with_core('CTracer')
        cov_instance = session.config.pluginmanager.get_plugin.return_value.cov_controller.cov
        cov_instance.sys_info.return_value = malformed_sys_info

        pytest_sessionstart(session)

        registered = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        assert any(isinstance(p, GremlinContextPlugin) for p in registered)

    @staticmethod
    def _piggyback_session_with_core(core: str) -> MagicMock:
        cov_instance = MagicMock(spec=coverage.Coverage)
        cov_instance.sys_info.return_value = [('core', core)]
        cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        cov_plugin.cov_controller.cov = cov_instance
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok
        _set_session(GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK))
        return session

    def it_registers_context_plugin_on_private_coverage_not_cov_plugin(self) -> None:
        """In PRIVATE mode, GremlinContextPlugin is registered on private coverage, not _cov's."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            mock_private_cov = MagicMock(spec=coverage.Coverage)
            mock_coverage_module.Coverage.return_value = mock_private_cov
            pytest_sessionstart(session)

        registered_plugins = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        context_plugins = [p for p in registered_plugins if isinstance(p, GremlinContextPlugin)]
        assert len(context_plugins) == 1
        assert context_plugins[0].cov is mock_private_cov

    def it_pins_the_private_coverage_to_the_ctrace_core(self) -> None:
        """PRIVATE mode requests ctrace so sysmon cannot drop per-test contexts (#531)."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            mock_private_cov = MagicMock(spec=coverage.Coverage)
            mock_coverage_module.Coverage.return_value = mock_private_cov
            pytest_sessionstart(session)

        mock_private_cov.set_option.assert_called_once_with('run:core', 'ctrace')

    def it_skips_registration_when_session_disabled(self) -> None:
        """No registration occurs when GremlinSession is disabled."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=False)
        _set_session(gs)

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()

    def it_skips_registration_when_no_session(self) -> None:
        """No registration occurs when no GremlinSession exists."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        _set_session(None)

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()

    def it_skips_registration_when_cov_controller_is_none(self) -> None:
        """PIGGYBACK mode with cov_controller=None does not raise AttributeError.

        pytest-cov sets cov_controller to None when the plugin is loaded but
        --cov was not passed.  _detect_coverage_mode returns PIGGYBACK whenever
        the '_cov' plugin object exists, so pytest_sessionstart must guard
        against cov_controller being None before accessing .cov on it.
        """
        cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        cov_plugin.cov_controller = None  # --cov not passed

        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        _set_session(gs)

        # Must not raise AttributeError: 'NoneType' object has no attribute 'cov'
        pytest_sessionstart(session)

        # No context plugin registered when there is no active coverage controller
        session.config.pluginmanager.register.assert_not_called()
