"""Warnings that must reach the terminal even though pytest captures log records.

The mutation run executes inside ``pytest_sessionfinish``, where pytest's logging plugin captures
``logger.warning`` records and prints none of them unless ``log_cli`` or ``--log-file`` is set. A warning
the user has to act on is logged with :data:`TERMINAL_NOTICE` as ``extra``; a :class:`TerminalNoticeHandler`
on the package logger then hands it to the session's terminal notices. The log record stays for anyone who
reads logs.
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Final,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PACKAGE_LOGGER_NAME: Final = 'pytest_gremlins'
TERMINAL_NOTICE: Final = MappingProxyType({'terminal_notice': True})
"""The ``extra=`` that marks a warning for the terminal.

The marked message is printed to the terminal as written, so never interpolate environment values, command
arguments or credential-bearing URLs into it.
"""
NOTICE_PREFIX: Final = 'pytest-gremlins: warning: '


def neutralize_control_characters(text: str) -> str:
    """Replace control characters (such as ESC) so untrusted text cannot drive the terminal."""
    return ''.join(char if char.isprintable() else '?' for char in text)


def _describe_cause(record: logging.LogRecord) -> str:
    """Render the exception logged with ``exc_info`` as `` (Type: message)`` on one line, or ``''`` without one."""
    cause = record.exc_info[1] if record.exc_info else None
    if cause is None:
        return ''
    try:
        raw_message = str(cause)
    except Exception:
        raw_message = ''
    message = neutralize_control_characters(' '.join(raw_message.split()))
    description = f'{type(cause).__name__}: {message}' if message else type(cause).__name__
    return f' ({description})'


class TerminalNoticeHandler(logging.Handler):
    """Forward each warning marked with :data:`TERMINAL_NOTICE` to ``queue_notice`` as one terminal line.

    Attaching a handler to the package logger stops logging from falling back to ``logging.lastResort``, which
    is what printed unmarked warnings before this handler existed. So every record the handler does not queue
    is passed to ``lastResort`` exactly when logging itself would have used it: when no handler other than a
    notice handler is on the chain, whatever the levels of the handlers that are. With several notice handlers
    on the chain, the first one forwards.
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
        try:
            if getattr(record, 'terminal_notice', False) and self._is_accepting():
                message = neutralize_control_characters(' '.join(record.getMessage().split()))
                self._queue_notice(f'{NOTICE_PREFIX}{message}{_describe_cause(record)}')
                return
            self._fall_back_to_last_resort(record)
        except Exception:
            self.handleError(record)

    def _fall_back_to_last_resort(self, record: logging.LogRecord) -> None:
        last_resort = logging.lastResort
        if last_resort is None or record.levelno < last_resort.level or not self._is_last_resort_turn(record):
            return
        last_resort.handle(record)

    def _is_last_resort_turn(self, record: logging.LogRecord) -> bool:
        """Say whether ``Logger.callHandlers`` would fall back to ``lastResort`` and this handler is the one to do it.

        ``callHandlers`` falls back only when the chain holds no handler at all, whatever their levels. Other
        notice handlers are not counted, so the first one on the chain forwards and the rest stay quiet.
        """
        first_notice_handler: TerminalNoticeHandler | None = None
        logger: logging.Logger | None = logging.getLogger(record.name)
        while logger is not None:
            for handler in logger.handlers:
                if not isinstance(handler, TerminalNoticeHandler):
                    return False
                if first_notice_handler is None:
                    first_notice_handler = handler
            logger = logger.parent if logger.propagate else None
        return first_notice_handler is self
