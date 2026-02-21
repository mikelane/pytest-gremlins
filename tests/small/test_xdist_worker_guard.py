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


@pytest.mark.small
class TestCollectionFinishWorkerGuard:
    """pytest_collection_finish returns early on xdist workers."""

    def test_collection_finish_skips_processing_on_xdist_worker(self) -> None:
        """Worker config causes pytest_collection_finish to return without modifying session."""
        session = MagicMock()
        session.config = MagicMock(spec=['workerinput'])
        session.config.workerinput = {'slaveid': 'gw0'}
        session.items = []

        gs = GremlinSession(enabled=True)
        gs.total_tests = 0
        _set_session(gs)

        with patch('pytest_gremlins.plugin._discover_source_files') as mock_discover:
            pytest_collection_finish(session)

        mock_discover.assert_not_called()

    def test_collection_finish_processes_normally_on_controller(self, tmp_path: Path) -> None:
        """Non-worker config causes pytest_collection_finish to proceed normally."""
        session = MagicMock()
        session.config = MagicMock(spec=[])
        session.config.rootdir = str(tmp_path)
        session.items = []

        gs = GremlinSession(enabled=True)
        _set_session(gs)

        with patch('pytest_gremlins.plugin._discover_source_files', return_value={}) as mock_discover:
            pytest_collection_finish(session)

        mock_discover.assert_called_once()


@pytest.mark.small
class TestSessionFinishWorkerGuard:
    """pytest_sessionfinish returns early on xdist workers."""

    def test_session_finish_skips_mutation_testing_on_xdist_worker(self) -> None:
        """Worker config causes pytest_sessionfinish to return without running mutations."""
        session = MagicMock()
        session.config = MagicMock(spec=['workerinput'])
        session.config.workerinput = {'slaveid': 'gw0'}

        gs = GremlinSession(enabled=True)
        gs.gremlins = [MagicMock()]
        _set_session(gs)

        with patch('pytest_gremlins.plugin._collect_coverage') as mock_collect:
            pytest_sessionfinish(session, exitstatus=0)

        mock_collect.assert_not_called()

    def test_session_finish_runs_mutation_testing_on_controller(self, tmp_path: Path) -> None:
        """Non-worker config causes pytest_sessionfinish to proceed with mutations."""
        session = MagicMock()
        session.config = MagicMock(spec=[])
        session.config.rootdir = str(tmp_path)

        gs = GremlinSession(enabled=True)
        gs.gremlins = [MagicMock()]
        _set_session(gs)

        with (
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]) as mock_run,
        ):
            pytest_sessionfinish(session, exitstatus=0)

        mock_run.assert_called_once()
