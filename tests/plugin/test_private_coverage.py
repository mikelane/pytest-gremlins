"""Tests for PRIVATE coverage mode lifecycle.

In PRIVATE mode (no --cov), pytest-gremlins creates and manages its own
coverage.Coverage instance inline:

1. pytest_sessionstart: creates Coverage(data_file=tmpdir, data_suffix=True)
   and registers GremlinContextPlugin on it.
2. pytest_runtestloop hookwrapper: starts coverage before tests, stops+saves after.
3. pytest_sessionfinish: reads the private coverage DB to build CoverageMap.
"""

from __future__ import annotations

import contextlib
from unittest.mock import (
    MagicMock,
    patch,
)

import coverage
import pytest

from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin
from pytest_gremlins.plugin import (
    CoverageMode,
    GremlinSession,
    _set_session,
    pytest_runtestloop,
    pytest_sessionstart,
)


@pytest.mark.small
class DescribeGremlinSessionPrivateCoverageField:
    """GremlinSession has a private_coverage field for the inline Coverage instance."""

    def it_initializes_private_coverage_to_none(self) -> None:
        """GremlinSession.private_coverage defaults to None."""
        gs = GremlinSession()
        assert gs.private_coverage is None

    def it_allows_setting_private_coverage(self) -> None:
        """GremlinSession.private_coverage can hold a Coverage instance."""
        cov = MagicMock(spec=coverage.Coverage)
        gs = GremlinSession(private_coverage=cov)
        assert gs.private_coverage is cov


@pytest.mark.small
class DescribePrivateModeSessionStart:
    """pytest_sessionstart creates and registers private coverage in PRIVATE mode."""

    def it_creates_coverage_instance_in_private_mode(self) -> None:
        """In PRIVATE mode, a Coverage instance is created and stored on the session."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            mock_cov = MagicMock(spec=coverage.Coverage)
            mock_coverage_module.Coverage.return_value = mock_cov
            pytest_sessionstart(session)

        assert gs.private_coverage is mock_cov

    def it_registers_context_plugin_on_private_coverage(self) -> None:
        """In PRIVATE mode, a GremlinContextPlugin is registered on the private Coverage."""
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            mock_cov = MagicMock(spec=coverage.Coverage)
            mock_coverage_module.Coverage.return_value = mock_cov
            pytest_sessionstart(session)

        registered = [call.args[0] for call in session.config.pluginmanager.register.call_args_list]
        context_plugins = [p for p in registered if isinstance(p, GremlinContextPlugin)]
        assert len(context_plugins) == 1
        assert context_plugins[0].cov is mock_cov

    def it_does_not_create_coverage_in_piggyback_mode(self) -> None:
        """In PIGGYBACK mode, no private Coverage instance is created."""
        cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        cov_plugin.cov_controller.cov = MagicMock(spec=coverage.Coverage)

        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = cov_plugin
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        _set_session(gs)

        with patch('pytest_gremlins.plugin.coverage') as mock_coverage_module:
            pytest_sessionstart(session)

        mock_coverage_module.Coverage.assert_not_called()
        assert gs.private_coverage is None


@pytest.mark.small
class DescribePrivateModeRuntestLoop:
    """pytest_runtestloop starts/stops private coverage around the test run."""

    def it_starts_coverage_before_tests_in_private_mode(self) -> None:
        """In PRIVATE mode, coverage.start() is called before the test loop yields."""
        mock_cov = MagicMock(spec=coverage.Coverage)
        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE, private_coverage=mock_cov)
        _set_session(gs)

        session = MagicMock(spec=pytest.Session)
        gen = pytest_runtestloop(session=session)
        next(gen)

        mock_cov.start.assert_called_once()

    def it_stops_and_saves_coverage_after_tests_in_private_mode(self) -> None:
        """In PRIVATE mode, coverage.stop() and save() are called after the test loop."""
        mock_cov = MagicMock(spec=coverage.Coverage)
        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE, private_coverage=mock_cov)
        _set_session(gs)

        session = MagicMock(spec=pytest.Session)
        gen = pytest_runtestloop(session=session)
        next(gen)
        with contextlib.suppress(StopIteration):
            next(gen)

        mock_cov.stop.assert_called_once()
        mock_cov.save.assert_called_once()

    def it_stop_before_save_order(self) -> None:
        """coverage.stop() must be called before coverage.save()."""
        call_order: list[str] = []
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov.stop.side_effect = lambda: call_order.append('stop')
        mock_cov.save.side_effect = lambda: call_order.append('save')

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE, private_coverage=mock_cov)
        _set_session(gs)

        session = MagicMock(spec=pytest.Session)
        gen = pytest_runtestloop(session=session)
        next(gen)
        with contextlib.suppress(StopIteration):
            next(gen)

        assert call_order == ['stop', 'save']

    def it_does_not_start_coverage_in_piggyback_mode(self) -> None:
        """In PIGGYBACK mode, private_coverage is None so no start() is called."""
        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK, private_coverage=None)
        _set_session(gs)

        session = MagicMock(spec=pytest.Session)
        gen = pytest_runtestloop(session=session)
        next(gen)
        with contextlib.suppress(StopIteration):
            next(gen)

    def it_does_not_touch_coverage_when_session_disabled(self) -> None:
        """When session is disabled, runtestloop hook is a no-op."""
        mock_cov = MagicMock(spec=coverage.Coverage)
        gs = GremlinSession(enabled=False, private_coverage=mock_cov)
        _set_session(gs)

        session = MagicMock(spec=pytest.Session)
        gen = pytest_runtestloop(session=session)
        next(gen)
        with contextlib.suppress(StopIteration):
            next(gen)

        mock_cov.start.assert_not_called()
        mock_cov.stop.assert_not_called()
