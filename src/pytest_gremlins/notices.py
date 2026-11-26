"""Warnings that must reach the terminal even though pytest captures log records.

The mutation run executes inside ``pytest_sessionfinish``, where pytest's logging plugin captures
``logger.warning`` records and prints none of them unless ``log_cli`` or ``--log-file`` is set. A warning
the user has to act on is logged with :data:`TERMINAL_NOTICE` as ``extra``; a :class:`TerminalNoticeHandler`
on the package logger then hands it to the session's terminal notices. The log record stays for anyone who
reads logs.
"""

from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Final,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PACKAGE_LOGGER_NAME: Final = 'pytest_gremlins'
TERMINAL_NOTICE: Final = {'terminal_notice': True}
NOTICE_PREFIX: Final = 'pytest-gremlins: warning: '


def neutralize_control_characters(text: str) -> str:
    """Replace control characters (such as ESC) so untrusted text cannot drive the terminal."""
    return ''.join(char if char.isprintable() else '?' for char in text)


class TerminalNoticeHandler(logging.Handler):
    """Forward each warning marked with :data:`TERMINAL_NOTICE` to ``queue_notice`` as one terminal line."""

    def __init__(self, queue_notice: Callable[[str], None]) -> None:
        """Create the handler.

        Args:
            queue_notice: Receives the finished terminal line for each marked warning.
        """
        super().__init__(level=logging.WARNING)
        self._queue_notice = queue_notice

    def emit(self, record: logging.LogRecord) -> None:
        """Queue the record's message when it is marked as a terminal notice."""
        if not getattr(record, 'terminal_notice', False):
            return
        message = neutralize_control_characters(' '.join(record.getMessage().split()))
        self._queue_notice(f'{NOTICE_PREFIX}{message}')
