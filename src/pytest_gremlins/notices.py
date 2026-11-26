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
    """Forward each warning marked with :data:`TERMINAL_NOTICE` to ``queue_notice`` as one terminal line.

    Attaching a handler to the package logger stops logging from falling back to ``logging.lastResort``, which
    is what printed unmarked warnings before this handler existed. So every record the handler does not queue
    is passed to ``lastResort`` exactly when no other handler would have handled it.
    """

    def __init__(
        self,
        queue_notice: Callable[[str], object],
        is_accepting: Callable[[], bool] = lambda: True,
    ) -> None:
        """Create the handler.

        Args:
            queue_notice: Receives the finished terminal line for each marked warning.
            is_accepting: Says whether the session behind ``queue_notice`` will print what it is given.
                A marked warning that is not accepted is treated like an unmarked one.
        """
        super().__init__(level=logging.WARNING)
        self._queue_notice = queue_notice
        self._is_accepting = is_accepting

    def emit(self, record: logging.LogRecord) -> None:
        """Queue a marked record, or keep any other record as visible as it was without this handler."""
        if getattr(record, 'terminal_notice', False) and self._is_accepting():
            message = neutralize_control_characters(' '.join(record.getMessage().split()))
            self._queue_notice(f'{NOTICE_PREFIX}{message}')
            return
        self._fall_back_to_last_resort(record)

    def _fall_back_to_last_resort(self, record: logging.LogRecord) -> None:
        last_resort = logging.lastResort
        if last_resort is None or record.levelno < last_resort.level or self._another_handler_takes(record):
            return
        last_resort.handle(record)

    def _another_handler_takes(self, record: logging.LogRecord) -> bool:
        logger: logging.Logger | None = logging.getLogger(record.name)
        while logger is not None:
            if any(handler is not self and record.levelno >= handler.level for handler in logger.handlers):
                return True
            logger = logger.parent if logger.propagate else None
        return False
