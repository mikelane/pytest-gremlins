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
