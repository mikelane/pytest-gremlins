"""The handler that turns marked warnings into terminal notices (issue #982)."""

from __future__ import annotations

import logging

import pytest

from pytest_gremlins.notices import (
    NOTICE_PREFIX,
    TERMINAL_NOTICE,
    TerminalNoticeHandler,
)


@pytest.fixture
def queued() -> list[str]:
    return []


@pytest.fixture
def logger(queued: list[str]) -> logging.Logger:
    notices_logger = logging.getLogger('test_notices_isolated')
    notices_logger.handlers = [TerminalNoticeHandler(queued.append)]
    notices_logger.propagate = False
    return notices_logger


@pytest.mark.small
class DescribeTerminalNoticeHandler:
    def it_queues_a_marked_warning_with_the_notice_prefix(self, logger: logging.Logger, queued: list[str]) -> None:
        logger.warning('cannot %s', 'write', extra=TERMINAL_NOTICE)

        assert queued == [f'{NOTICE_PREFIX}cannot write']

    def it_ignores_a_warning_that_is_not_marked(self, logger: logging.Logger, queued: list[str]) -> None:
        logger.warning('debug detail')

        assert queued == []

    def it_ignores_a_marked_record_below_warning(self, logger: logging.Logger, queued: list[str]) -> None:
        logger.setLevel(logging.INFO)

        logger.info('fyi', extra=TERMINAL_NOTICE)

        assert queued == []

    def it_neutralizes_control_characters_and_joins_lines(self, logger: logging.Logger, queued: list[str]) -> None:
        logger.warning('bad\x1b[31m path\n  continued', extra=TERMINAL_NOTICE)

        assert queued == [f'{NOTICE_PREFIX}bad?[31m path continued']


class _Recorder(logging.Handler):
    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def last_resort(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder(logging.WARNING)
    monkeypatch.setattr(logging, 'lastResort', recorder)
    return recorder


def _isolated_logger(name: str, monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """Register a parentless logger; pytest attaches its capture handler to every non-propagating one."""
    isolated = logging.Logger(name)  # noqa: LOG001
    monkeypatch.setitem(logging.Logger.manager.loggerDict, name, isolated)
    return isolated


@pytest.fixture
def package_logger(queued: list[str], monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    notices_logger = _isolated_logger('test_notices_forwarding', monkeypatch)
    notices_logger.addHandler(TerminalNoticeHandler(queued.append))
    return notices_logger


@pytest.mark.small
class DescribeLastResortForwarding:
    def it_forwards_an_unmarked_warning_when_no_other_handler_takes_it(
        self, package_logger: logging.Logger, last_resort: _Recorder
    ) -> None:
        package_logger.warning('unmarked')

        assert last_resort.messages == ['unmarked']

    def it_does_not_forward_a_queued_notice(
        self, package_logger: logging.Logger, last_resort: _Recorder, queued: list[str]
    ) -> None:
        package_logger.warning('marked', extra=TERMINAL_NOTICE)

        assert (queued, last_resort.messages) == ([f'{NOTICE_PREFIX}marked'], [])

    def it_does_not_forward_when_another_handler_on_the_logger_takes_it(
        self, package_logger: logging.Logger, last_resort: _Recorder
    ) -> None:
        other = _Recorder()
        package_logger.addHandler(other)

        package_logger.warning('unmarked')

        assert (other.messages, last_resort.messages) == (['unmarked'], [])

    def it_does_not_forward_when_a_propagated_ancestor_handler_takes_it(
        self, package_logger: logging.Logger, last_resort: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parent = _isolated_logger('test_notices_forwarding_parent', monkeypatch)
        ancestor = _Recorder()
        parent.addHandler(ancestor)
        package_logger.parent = parent
        package_logger.propagate = True

        package_logger.warning('unmarked')

        assert (ancestor.messages, last_resort.messages) == (['unmarked'], [])

    def it_forwards_when_an_ancestor_handler_is_cut_off_by_propagate_false(
        self, package_logger: logging.Logger, last_resort: _Recorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parent = _isolated_logger('test_notices_forwarding_parent', monkeypatch)
        parent.addHandler(_Recorder())
        package_logger.parent = parent
        package_logger.propagate = False

        package_logger.warning('unmarked')

        assert last_resort.messages == ['unmarked']

    def it_forwards_when_the_only_other_handler_is_above_the_record_level(
        self, package_logger: logging.Logger, last_resort: _Recorder
    ) -> None:
        package_logger.addHandler(_Recorder(logging.ERROR))

        package_logger.warning('unmarked')

        assert last_resort.messages == ['unmarked']

    def it_forwards_a_marked_warning_the_session_will_not_print(
        self, last_resort: _Recorder, queued: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notices_logger = _isolated_logger('test_notices_forwarding_declined', monkeypatch)
        notices_logger.addHandler(TerminalNoticeHandler(queued.append, lambda: False))

        notices_logger.warning('declined', extra=TERMINAL_NOTICE)

        assert (queued, last_resort.messages) == ([], ['declined'])
