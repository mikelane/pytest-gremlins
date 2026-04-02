"""Tests that pardoned gremlins appear in terminal output and strict_pardons works."""

from __future__ import annotations

import ast
from unittest.mock import MagicMock

from _pytest.terminal import TerminalReporter
import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _set_session,
    pytest_terminal_summary,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


def _make_pardoned_gremlin() -> Gremlin:
    node = ast.parse('a // b', mode='eval').body
    return Gremlin(
        gremlin_id='g_term_001',
        file_path='src/example.py',
        line_number=5,
        original_node=node,
        mutated_node=node,
        operator_name='arithmetic',
        description='// to /',
        pardoned=True,
        pardon_reason='equivalent: floor division is integer arithmetic',
    )


def _make_survived_gremlin() -> Gremlin:
    node = ast.parse('a < b', mode='eval').body
    return Gremlin(
        gremlin_id='g_term_002',
        file_path='src/example.py',
        line_number=10,
        original_node=node,
        mutated_node=node,
        operator_name='comparison',
        description='< to <=',
    )


@pytest.mark.small
class DescribeTerminalSummaryPardoned:
    """Terminal summary must display pardoned count when pardons exist."""

    def it_displays_pardoned_count_line_when_pardons_exist(self) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        written_lines: list[str] = []
        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None
        tr.write_line.side_effect = written_lines.append

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        pardoned_lines = [line for line in written_lines if 'Pardoned' in line or 'pardoned' in line]
        assert pardoned_lines, f'No pardoned line found in terminal output: {written_lines}'
        assert any('1' in line for line in pardoned_lines), f'Pardoned count (1) not shown in output: {pardoned_lines}'

    def it_does_not_display_pardoned_line_when_no_pardons(self) -> None:
        gremlin = _make_survived_gremlin()
        survived = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)
        session = GremlinSession(enabled=True, gremlins=[gremlin], results=[survived])
        _set_session(session)

        written_lines: list[str] = []
        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None
        tr.write_line.side_effect = written_lines.append

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert not any('Pardoned' in line or 'pardoned' in line for line in written_lines), (
            f'Unexpected pardoned line in terminal output: {written_lines}'
        )


@pytest.mark.small
class DescribeAuditPardonsTerminalListing:
    """--gremlin-audit-pardons must print each pardoned gremlin's details."""

    def it_shows_file_line_and_reason_for_each_pardoned_gremlin(self) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, audit_pardons=True, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        written_lines: list[str] = []
        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None
        tr.write_line.side_effect = written_lines.append

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        output = '\n'.join(written_lines)
        assert 'src/example.py' in output, f'File path missing from audit output: {written_lines}'
        assert '5' in output, f'Line number missing from audit output: {written_lines}'
        assert 'equivalent: floor division is integer arithmetic' in output, (
            f'Pardon reason missing from audit output: {written_lines}'
        )

    def it_does_not_show_audit_listing_when_flag_is_false(self) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, audit_pardons=False, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        written_lines: list[str] = []
        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None
        tr.write_line.side_effect = written_lines.append

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert not any('equivalent: floor division' in line for line in written_lines), (
            f'Audit output appeared when audit_pardons=False: {written_lines}'
        )


@pytest.mark.small
class DescribeStrictPardonsCIFailure:
    """--strict-pardons must cause non-zero exit when any pardons exist."""

    def it_calls_pytest_exit_when_strict_pardons_true_and_pardons_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, strict_pardons=True, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        exit_calls: list[tuple[str, int]] = []

        def fake_exit(msg: str, returncode: int = 1) -> None:  # type: ignore[misc]
            exit_calls.append((msg, returncode))

        monkeypatch.setattr(pytest, 'exit', fake_exit)

        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert len(exit_calls) == 1, 'pytest.exit was not called for strict_pardons=True with pardons'
        assert exit_calls[0][1] == 1, f'Expected exit returncode 1, got {exit_calls[0][1]}'

    def it_exit_message_includes_pardoned_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, strict_pardons=True, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        exit_calls: list[tuple[str, int]] = []

        def fake_exit(msg: str, returncode: int = 1) -> None:  # type: ignore[misc]
            exit_calls.append((msg, returncode))

        monkeypatch.setattr(pytest, 'exit', fake_exit)

        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert len(exit_calls) == 1
        assert '1' in exit_calls[0][0], f'Exit message missing count: {exit_calls[0][0]}'

    def it_does_not_exit_when_strict_pardons_false_and_pardons_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gremlin = _make_pardoned_gremlin()
        pardoned = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
        session = GremlinSession(enabled=True, strict_pardons=False, gremlins=[gremlin], results=[pardoned])
        _set_session(session)

        exit_calls: list[tuple[str, int]] = []

        def fake_exit(msg: str, returncode: int = 1) -> None:  # type: ignore[misc]
            exit_calls.append((msg, returncode))

        monkeypatch.setattr(pytest, 'exit', fake_exit)

        tr = MagicMock(spec=TerminalReporter)
        tr.config = MagicMock()  # TerminalReporter.config is set in __init__; bare-mock: ok
        tr.config.getoption.return_value = None
        tr.config.pluginmanager.get_plugin.return_value = None

        pytest_terminal_summary(tr, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert len(exit_calls) == 0, 'pytest.exit was called unexpectedly when strict_pardons=False'
