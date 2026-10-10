"""Unit tests for the skipped-file terminal notice helpers (issue #638)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import (
    MagicMock,
    call,
    patch,
)

from _pytest.terminal import TerminalReporter
import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _describe_exception,
    _generate_gremlins,
    _printable,
    _report_to_terminal,
    _write_empty_run_report,
    pytest_terminal_summary,
)


def _written_lines(reporter: MagicMock) -> list[str]:
    return [written.args[0] for written in reporter.write_line.call_args_list]


@pytest.mark.small
class DescribeDescribeException:
    def it_joins_type_and_message(self) -> None:
        assert _describe_exception(ValueError('boom')) == 'ValueError: boom'

    def it_collapses_a_multiline_message_to_one_line(self) -> None:
        assert _describe_exception(RuntimeError('first\n  second')) == 'RuntimeError: first second'

    def it_renders_only_the_type_when_the_message_is_empty(self) -> None:
        assert _describe_exception(KeyError()) == 'KeyError'

    def it_renders_only_the_type_when_the_message_is_whitespace(self) -> None:
        assert _describe_exception(ValueError('  \n ')) == 'ValueError'


@pytest.mark.small
class DescribeTerminalSafety:
    def it_replaces_escape_characters_in_an_exception_message(self) -> None:
        assert _describe_exception(ValueError('a\x1b[31mred')) == 'ValueError: a?[31mred'

    def it_replaces_escape_characters_in_a_skipped_path(self) -> None:
        assert _printable('src/\x1b]0;pwn\x07.py') == 'src/?]0;pwn?.py'

    @pytest.mark.parametrize(
        ('text', 'expected'),
        [
            pytest.param('line\nbreak', 'line?break', id='newline'),
            pytest.param('tab\there', 'tab?here', id='tab'),
            pytest.param('carriage\rreturn', 'carriage?return', id='carriage-return'),
            pytest.param('nul\x00byte', 'nul?byte', id='nul'),
            pytest.param('del\x7fchar', 'del?char', id='delete'),
        ],
    )
    def it_replaces_each_control_character_with_a_question_mark(self, text: str, expected: str) -> None:
        assert _printable(text) == expected

    @pytest.mark.parametrize(
        'text',
        [
            pytest.param('src/caf\u00e9.py', id='latin-accent'),
            pytest.param('src/\u6a21\u5757.py', id='cjk'),
            pytest.param('src/my module.py', id='space'),
            pytest.param('', id='empty'),
        ],
    )
    def it_leaves_printable_text_unchanged(self, text: str) -> None:
        assert _printable(text) == text


@pytest.mark.small
class DescribeReportToTerminal:
    def it_queues_a_message(self) -> None:
        session = GremlinSession()

        _report_to_terminal(session, 'hello')

        assert session.terminal_notices == ['hello']

    def it_queues_a_repeated_message_once(self) -> None:
        session = GremlinSession()

        _report_to_terminal(session, 'hello')
        _report_to_terminal(session, 'hello')

        assert session.terminal_notices == ['hello']


@pytest.mark.small
class DescribeGenerateGremlinsSkipRecording:
    """A file whose instrumentation raises is recorded and queued for the terminal (issue #638)."""

    def it_records_the_skipped_file_with_its_reason(self) -> None:
        session = GremlinSession(enabled=True)

        with patch('pytest_gremlins.plugin.transform_source', side_effect=ValueError('boom')):
            _generate_gremlins(session, {'bad_file.py': 'x = 1'}, Path('/fake/root'))

        assert session.skipped_files == {'bad_file.py': 'ValueError: boom'}

    def it_queues_a_terminal_notice_naming_the_file_and_reason(self) -> None:
        session = GremlinSession(enabled=True)

        with patch('pytest_gremlins.plugin.transform_source', side_effect=ValueError('boom')):
            _generate_gremlins(session, {'bad_file.py': 'x = 1'}, Path('/fake/root'))

        assert session.terminal_notices == [
            'pytest-gremlins: skipped bad_file.py: could not instrument (ValueError: boom)'
        ]

    def it_neutralizes_control_characters_in_the_queued_notice_path(self) -> None:
        session = GremlinSession(enabled=True)

        with patch('pytest_gremlins.plugin.transform_source', side_effect=ValueError('boom')):
            _generate_gremlins(session, {'bad\x1b[2Jfile.py': 'x = 1'}, Path('/fake/root'))

        assert session.terminal_notices == [
            'pytest-gremlins: skipped bad?[2Jfile.py: could not instrument (ValueError: boom)'
        ]

    def it_records_every_skipped_file(self) -> None:
        session = GremlinSession(enabled=True)

        with patch('pytest_gremlins.plugin.transform_source', side_effect=RecursionError('too deep')):
            _generate_gremlins(session, {'a.py': 'x = 1', 'b.py': 'y = 2'}, Path('/fake/root'))

        assert session.skipped_files == {'a.py': 'RecursionError: too deep', 'b.py': 'RecursionError: too deep'}


@pytest.mark.small
class DescribeWriteEmptyRunReport:
    """A run with no gremlins explains why, and skipped files take precedence over "nothing found"."""

    def it_lists_skipped_files_with_a_count(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(
            enabled=True,
            target_paths=[Path('src/demo')],
            skipped_files={'src/demo/a.py': 'ValueError: x', 'src/demo/b.py': 'ValueError: y'},
        )

        _write_empty_run_report(reporter, session)

        assert _written_lines(reporter) == [
            '',
            '2 file(s) skipped and not mutation tested:',
            '  - src/demo/a.py',
            '  - src/demo/b.py',
            '',
        ]

    def it_neutralizes_control_characters_in_listed_skipped_paths(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(enabled=True, skipped_files={'src/\x1b[31mred.py': 'ValueError: x'})

        _write_empty_run_report(reporter, session)

        assert '  - src/?[31mred.py' in _written_lines(reporter)

    def it_lists_searched_paths_when_nothing_was_skipped(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(enabled=True, target_paths=[Path('src/demo')])

        _write_empty_run_report(reporter, session)

        assert _written_lines(reporter) == [
            '',
            'No gremlins found in source code. Searched paths:',
            f'  - {Path("src/demo")}',
            '',
        ]

    def it_explains_target_discovery_when_no_paths_were_found(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(enabled=True)

        _write_empty_run_report(reporter, session)

        assert _written_lines(reporter)[1] == 'No gremlins found: no source paths were discovered.'

    def it_frames_the_report_with_separators(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(enabled=True, skipped_files={'a.py': 'ValueError: x'})

        _write_empty_run_report(reporter, session)

        assert reporter.write_sep.call_args_list == [call('=', 'pytest-gremlins mutation report'), call('=', '')]


@pytest.mark.small
class DescribeTerminalSummaryNotices:
    """Queued notices are written before the mutation report."""

    def it_writes_queued_notices_before_the_empty_run_report(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(
            enabled=True,
            terminal_notices=['notice one', 'notice two'],
            skipped_files={'a.py': 'ValueError: x'},
        )

        with patch('pytest_gremlins.plugin._get_session', return_value=session):
            pytest_terminal_summary(reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert _written_lines(reporter)[:3] == ['notice one', 'notice two', '']

    def it_writes_nothing_when_the_session_is_disabled(self) -> None:
        reporter = MagicMock(spec=TerminalReporter)
        session = GremlinSession(enabled=False, terminal_notices=['notice one'])

        with patch('pytest_gremlins.plugin._get_session', return_value=session):
            pytest_terminal_summary(reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        reporter.write_line.assert_not_called()
