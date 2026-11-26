"""Each warning a user must act on is logged as a terminal notice (issue #982).

Only records logged with ``extra=TERMINAL_NOTICE`` reach the terminal, so a call site that loses the marker goes
back to being hidden by pytest's log capture. These tests pin the marker on every call site the end-to-end tests in
``tests/plugin/test_runtime_warnings_visible_by_default.py`` do not run.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess

import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.control_run import (
    run_control,
    run_unmutated,
)
from pytest_gremlins.instrumentation.pragma import parse_pardoned_lines
from pytest_gremlins.parallel import worker_kill
from pytest_gremlins.reporting.history import (
    append_history_entry,
    load_history,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import read_source


def _only_warning(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    """Return the single warning the act phase logged."""
    assert len(caplog.records) == 1, caplog.messages
    return caplog.records[0]


def _is_terminal_notice(record: logging.LogRecord) -> bool:
    return getattr(record, 'terminal_notice', False) is True


def _refuse_to_launch(*_args: object, **_kwargs: object) -> object:
    raise OSError('no such interpreter')


@pytest.mark.small
class DescribePragmaWarningsAreTerminalNotices:
    @pytest.mark.parametrize(
        ('source', 'expected'),
        [
            ('x = 1  # gremlin: pardon[no-such-code] because\n', 'has unknown reason code'),
            ('x = 1  # gremlin: pardon[equivalent]\n', 'is missing a justification'),
            ('x = 1\n# gremlin: pardon[equivalent] same value\n', 'no code line below'),
            ('# gremlin: pardon[equivalent] same value\n\nx = 1\n', 'blank line follows'),
            (
                '# gremlin: pardon[equivalent] above\nx = 1  # gremlin: pardon[equivalent] same line\n',
                'duplicate pardon',
            ),
        ],
    )
    def it_marks_the_pragma_warning_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, source: str, expected: str
    ) -> None:
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma')

        parse_pardoned_lines(source, file_path='target.py')

        record = _only_warning(caplog)
        assert expected in record.getMessage()
        assert _is_terminal_notice(record)


@pytest.mark.small
class DescribeControlRunWarningsAreTerminalNotices:
    def it_marks_a_control_run_that_cannot_launch_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(process_tree, 'run_bounded', _refuse_to_launch)
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.control_run')

        run_control(['python'], [], Path(), {})

        record = _only_warning(caplog)
        assert record.getMessage() == 'Could not run the unmutated control run: no such interpreter'
        assert _is_terminal_notice(record)

    def it_marks_an_unmutated_run_that_cannot_launch_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(process_tree, 'run_bounded', _refuse_to_launch)
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.control_run')

        run_unmutated(['python'], [], Path(), {}, timeout=1)

        record = _only_warning(caplog)
        assert record.getMessage() == 'Could not run the unmutated selection to confirm a timeout: no such interpreter'
        assert _is_terminal_notice(record)


@pytest.mark.small
class DescribeWorkerKillWarningsAreTerminalNotices:
    @pytest.mark.parametrize(
        ('error', 'expected'),
        [
            (PermissionError('denied'), 'Not permitted to kill process 4242; it may outlive the run.'),
            (OSError('broken'), 'Cannot kill process 4242 (broken); it may outlive the run.'),
        ],
    )
    def it_marks_a_refused_kill_as_a_terminal_notice(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        error: OSError,
        expected: str,
    ) -> None:
        def refuse_kill(_pid: int, _signal: int) -> None:
            raise error

        monkeypatch.setattr(os, 'kill', refuse_kill)
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.parallel.worker_kill')

        worker_kill.sigkill_pids([4242])

        record = _only_warning(caplog)
        assert record.getMessage() == expected
        assert _is_terminal_notice(record)


@pytest.mark.medium
class DescribeTaskkillWarningIsTerminalNotice:
    """Medium because it replaces ``subprocess.run``, which small tests may not leave patched."""

    def it_marks_a_taskkill_that_cannot_run_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', True)
        monkeypatch.setattr(subprocess, 'run', _refuse_to_launch)
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.parallel.worker_kill')

        worker_kill.kill_process_trees([4242])

        record = _only_warning(caplog)
        assert record.getMessage() == 'Cannot run taskkill on worker 4242; its test command may outlive it.'
        assert _is_terminal_notice(record)


@pytest.mark.medium
class DescribeReportWarningsAreTerminalNotices:
    def it_marks_an_unreadable_history_on_load_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not valid json', encoding='utf-8')
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.reporting.history')

        load_history(corrupt)

        record = _only_warning(caplog)
        assert record.getMessage() == f'Could not load history from {corrupt}'
        assert _is_terminal_notice(record)

    def it_marks_an_unreadable_history_on_append_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not valid json', encoding='utf-8')
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.reporting.history')

        append_history_entry(rootdir=tmp_path, score=MutationScore.from_results([]), history_path=corrupt)

        record = _only_warning(caplog)
        assert record.getMessage() == f'Could not read existing history from {corrupt}, starting fresh'
        assert _is_terminal_notice(record)

    def it_marks_an_unreadable_stryker_source_as_a_terminal_notice(
        self, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        missing = str(tmp_path / 'missing.py')
        caplog.set_level(logging.WARNING, logger='pytest_gremlins.reporting.stryker_export')

        read_source(missing)

        record = _only_warning(caplog)
        assert record.getMessage() == f'Could not read {missing} for the Stryker report; exporting empty source'
        assert _is_terminal_notice(record)
