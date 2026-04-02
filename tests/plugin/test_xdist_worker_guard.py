"""Tests for xdist worker guard behaviour in plugin hooks.

When pytest-gremlins runs inside an xdist worker process both
``pytest_collection_finish`` and ``pytest_sessionfinish`` must return early
without touching GremlinSession state.  This prevents double-execution on
every worker and keeps mutation testing centralised on the controller.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _set_session,
    pytest_collection_finish,
    pytest_sessionfinish,
)


def _make_controller_session(tmp_path: Path) -> MagicMock:
    """Build a mock pytest.Session configured as an xdist controller (no workerinput)."""
    mock_pluginmanager = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
    mock_pluginmanager.get_plugin.return_value = None
    mock_config = MagicMock(spec=['rootdir', 'pluginmanager'])
    mock_config.rootdir = str(tmp_path)
    mock_config.pluginmanager = mock_pluginmanager
    session = MagicMock(spec=pytest.Session)
    session.config = mock_config
    return session


@pytest.mark.small
class DescribeCollectionFinishWorkerGuard:
    """pytest_collection_finish returns early on xdist workers."""

    def it_collection_finish_skips_processing_on_xdist_worker(self) -> None:
        """Worker config causes pytest_collection_finish to return without modifying session."""
        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock(spec=['workerinput'])
        session.config.workerinput = {'slaveid': 'gw0'}
        session.items = []

        gs = GremlinSession(enabled=True)
        gs.total_tests = 0
        _set_session(gs)

        with patch('pytest_gremlins.plugin._discover_source_files') as mock_discover:
            pytest_collection_finish(session)

        mock_discover.assert_not_called()

    def it_collection_finish_processes_normally_on_controller(self, tmp_path: Path) -> None:
        """Non-worker config causes pytest_collection_finish to proceed normally."""
        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock(spec=[])
        session.config.rootdir = str(tmp_path)
        session.items = []

        gs = GremlinSession(enabled=True)
        _set_session(gs)

        with patch('pytest_gremlins.plugin._discover_source_files', return_value={}) as mock_discover:
            pytest_collection_finish(session)

        mock_discover.assert_called_once()


@pytest.mark.small
class DescribeSessionFinishWorkerGuard:
    """pytest_sessionfinish returns early on xdist workers."""

    def it_skips_mutation_testing_on_xdist_worker(self) -> None:
        """Worker config causes pytest_sessionfinish to return without running mutations."""
        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock(spec=['workerinput'])
        session.config.workerinput = {'slaveid': 'gw0'}

        gs = GremlinSession(enabled=True)
        gs.gremlins = [MagicMock()]  # opaque filler: attrs never accessed; bare-mock: ok
        _set_session(gs)

        with patch('pytest_gremlins.plugin._collect_coverage') as mock_collect:
            pytest_sessionfinish(session, exitstatus=0)

        mock_collect.assert_not_called()

    def it_runs_mutation_testing_on_controller(self, tmp_path: Path) -> None:
        """Non-worker config causes pytest_sessionfinish to proceed with mutations."""
        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock(spec=[])
        session.config.rootdir = str(tmp_path)
        session.config.pluginmanager = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
        session.config.pluginmanager.get_plugin.return_value = None

        gs = GremlinSession(enabled=True)
        gs.gremlins = [MagicMock()]  # opaque filler: attrs never accessed; bare-mock: ok
        _set_session(gs)

        with (
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]) as mock_run,
        ):
            pytest_sessionfinish(session, exitstatus=0)

        mock_run.assert_called_once()


@pytest.mark.small
class DescribeSessionFinishBranches:
    """pytest_sessionfinish early-return guards and execution mode selection."""

    def it_returns_early_when_no_gremlins(self, tmp_path: Path) -> None:
        """When gremlin_session.gremlins is empty, sessionfinish returns before collecting coverage."""
        session = _make_controller_session(tmp_path)

        gs = GremlinSession(enabled=True)
        # gremlins is empty by default
        _set_session(gs)

        with patch('pytest_gremlins.plugin._collect_coverage') as mock_collect:
            pytest_sessionfinish(session, exitstatus=0)

        mock_collect.assert_not_called()

    def it_calls_batch_testing_when_batch_enabled(self, tmp_path: Path) -> None:
        """When batch_enabled is True, _run_batch_mutation_testing is called."""
        session = _make_controller_session(tmp_path)

        gs = GremlinSession(enabled=True, batch_enabled=True)
        gs.gremlins = [MagicMock()]  # opaque filler: attrs never accessed; bare-mock: ok
        _set_session(gs)

        with (
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_batch_mutation_testing', return_value=[]) as mock_batch,
            patch('pytest_gremlins.plugin._run_parallel_mutation_testing') as mock_parallel,
            patch('pytest_gremlins.plugin._run_mutation_testing') as mock_serial,
        ):
            pytest_sessionfinish(session, exitstatus=0)

        mock_batch.assert_called_once()
        mock_parallel.assert_not_called()
        mock_serial.assert_not_called()

    def it_calls_parallel_testing_when_parallel_enabled(self, tmp_path: Path) -> None:
        """When parallel_enabled is True and batch_enabled is False, _run_parallel_mutation_testing is called."""
        session = _make_controller_session(tmp_path)

        gs = GremlinSession(enabled=True, parallel_enabled=True, batch_enabled=False)
        gs.gremlins = [MagicMock()]  # opaque filler: attrs never accessed; bare-mock: ok
        _set_session(gs)

        with (
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_batch_mutation_testing') as mock_batch,
            patch('pytest_gremlins.plugin._run_parallel_mutation_testing', return_value=[]) as mock_parallel,
            patch('pytest_gremlins.plugin._run_mutation_testing') as mock_serial,
        ):
            pytest_sessionfinish(session, exitstatus=0)

        mock_batch.assert_not_called()
        mock_parallel.assert_called_once()
        mock_serial.assert_not_called()
