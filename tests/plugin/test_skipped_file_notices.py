"""Unit tests for the skipped-file terminal notice helpers (issue #638)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _describe_exception,
    _printable,
    _report_to_terminal,
)


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
