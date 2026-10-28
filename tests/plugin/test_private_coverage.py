"""Tests that PRIVATE coverage mode keeps no inline coverage instance (#533).

Nothing read the data a PRIVATE-mode ``coverage.Coverage(data_suffix=True)`` saved: the only
coverage reader opens the pre-scan's ``.coverage`` file. The instance cost tracing overhead,
left stray ``.coverage.*`` files and, with ``COVERAGE_FILE`` set, polluted the user's data.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

import pytest_gremlins.plugin as plugin_module
from pytest_gremlins.plugin import (
    CoverageMode,
    GremlinSession,
    _set_session,
    pytest_sessionstart,
)


@pytest.mark.small
class DescribePrivateModeSessionStart:
    """pytest_sessionstart creates no coverage instance and registers nothing in PRIVATE mode."""

    def it_creates_no_coverage_instance_in_private_mode(self) -> None:
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok
        _set_session(GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE))

        with patch('coverage.Coverage') as mock_coverage_class:
            pytest_sessionstart(session)

        mock_coverage_class.assert_not_called()

    def it_registers_no_plugin_in_private_mode(self) -> None:
        session = MagicMock(spec=pytest.Session)
        session.config.pluginmanager.get_plugin.return_value = None
        session.config.pluginmanager.register = MagicMock()  # method mock on chained attr; bare-mock: ok
        _set_session(GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE))

        pytest_sessionstart(session)

        session.config.pluginmanager.register.assert_not_called()


@pytest.mark.small
class DescribePrivateCoverageRemoval:
    """The private coverage field and test-loop wrapper no longer exist."""

    def it_has_no_private_coverage_field_on_the_session(self) -> None:
        assert 'private_coverage' not in {f.name for f in dataclasses.fields(GremlinSession)}

    def it_has_no_runtestloop_hook(self) -> None:
        assert not hasattr(plugin_module, 'pytest_runtestloop')

    def it_has_no_tmpdir_field_for_worker_coverage_data_on_the_session(self) -> None:
        assert 'gremlins_tmpdir' not in {f.name for f in dataclasses.fields(GremlinSession)}

    def it_has_no_worker_input_injection_for_worker_coverage_data(self) -> None:
        assert not hasattr(plugin_module, '_XdistWorkerNode')
