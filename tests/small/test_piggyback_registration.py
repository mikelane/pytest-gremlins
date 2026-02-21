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

import pytest

from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin
from pytest_gremlins.plugin import (
    CoverageMode,
    GremlinSession,
    _set_session,
    pytest_sessionstart,
)


@pytest.mark.small
class TestGremlinSessionCoverageMode:
    """GremlinSession stores coverage_mode field."""

    def test_default_coverage_mode_is_private(self) -> None:
        """GremlinSession defaults to PRIVATE mode when no mode specified."""
        gs = GremlinSession()
        assert gs.coverage_mode == CoverageMode.PRIVATE

    def test_coverage_mode_can_be_set_to_piggyback(self) -> None:
        """GremlinSession accepts PIGGYBACK mode."""
        gs = GremlinSession(coverage_mode=CoverageMode.PIGGYBACK)
        assert gs.coverage_mode == CoverageMode.PIGGYBACK

    def test_piggyback_and_private_are_distinct_in_session(self) -> None:
        """PIGGYBACK and PRIVATE produce different session states."""
        gs_piggyback = GremlinSession(coverage_mode=CoverageMode.PIGGYBACK)
        gs_private = GremlinSession(coverage_mode=CoverageMode.PRIVATE)
        assert gs_piggyback.coverage_mode != gs_private.coverage_mode


@pytest.mark.small
class TestPiggybackContextPluginRegistration:
    """pytest_sessionstart registers GremlinContextPlugin in PIGGYBACK mode."""

    def test_registers_context_plugin_when_cov_plugin_present(self) -> None:
        """When _cov plugin exists, registers GremlinContextPlugin on its coverage."""
        cov_controller = MagicMock()
        cov_instance = MagicMock()
        cov_controller.cov = cov_instance

        cov_plugin = MagicMock()
        cov_plugin.cov_controller = cov_controller

        session = MagicMock()
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        _set_session(gs)

        pytest_sessionstart(session)

        registered_plugins = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        context_plugins = [p for p in registered_plugins if isinstance(p, GremlinContextPlugin)]
        assert len(context_plugins) == 1
        assert context_plugins[0].cov is cov_instance

    def test_registers_context_plugin_on_private_coverage_not_cov_plugin(self) -> None:
        """In PRIVATE mode, GremlinContextPlugin is registered on private coverage, not _cov's."""
        session = MagicMock()
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            mock_private_cov = MagicMock()
            mock_coverage_module.Coverage.return_value = mock_private_cov
            pytest_sessionstart(session)

        registered_plugins = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        context_plugins = [p for p in registered_plugins if isinstance(p, GremlinContextPlugin)]
        assert len(context_plugins) == 1
        assert context_plugins[0].cov is mock_private_cov

    def test_skips_registration_when_session_disabled(self) -> None:
        """No registration occurs when GremlinSession is disabled."""
        session = MagicMock()
        session.config.pluginmanager.register = MagicMock()

        gs = GremlinSession(enabled=False)
        _set_session(gs)

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()

    def test_skips_registration_when_no_session(self) -> None:
        """No registration occurs when no GremlinSession exists."""
        session = MagicMock()
        session.config.pluginmanager.register = MagicMock()

        _set_session(None)

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()

    def test_skips_registration_when_cov_controller_is_none(self) -> None:
        """PIGGYBACK mode with cov_controller=None does not raise AttributeError.

        pytest-cov sets cov_controller to None when the plugin is loaded but
        --cov was not passed.  _detect_coverage_mode returns PIGGYBACK whenever
        the '_cov' plugin object exists, so pytest_sessionstart must guard
        against cov_controller being None before accessing .cov on it.
        """
        cov_plugin = MagicMock()
        cov_plugin.cov_controller = None  # --cov not passed

        session = MagicMock()
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        _set_session(gs)

        # Must not raise AttributeError: 'NoneType' object has no attribute 'cov'
        pytest_sessionstart(session)

        # No context plugin registered when there is no active coverage controller
        session.config.pluginmanager.register.assert_not_called()
