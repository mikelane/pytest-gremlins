"""Flush policy that keeps cached results durable while a long run is still going (issue #974)."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

FLUSH_EVERY_RESULTS = 25
"""Results that may wait in memory before a flush.

One flush is one SQLite transaction, a few milliseconds, while a gremlin takes seconds to run, so the
cost is far below 1% of a run. A kill that arrives between flushes loses at most this many results.
"""

FLUSH_EVERY_SECONDS = 5.0
"""Longest a result waits in memory before a flush.

Bounds the loss when gremlins finish slowly, and when a parallel run stalls on a single stuck gremlin,
which is the case that motivated the policy. The sequential runner flushes between gremlins, so it
can lose up to this long plus the running gremlin's own time (at most ``mutant_timeout``).
"""


class PeriodicFlusher:
    """Calls ``flush`` after enough results or enough time, whichever comes first.

    The owner calls :meth:`note_result` after each deferred cache write and :meth:`flush_if_due` at least
    once per ``every_seconds``. Nothing here is thread-safe: call it from the thread that owns the cache
    connection.

    A flush that fails (disk full, database locked) never raises: the first failure is logged as a warning
    and later ones at DEBUG, the pending results stay pending, and the next flush retries them. The cache's
    own ``close()`` still retries them last, which is where a persistent failure surfaces. After a failure
    :meth:`flush_if_due` waits a full interval before trying again, so a broken disk is not hit on every result.

    Args:
        flush: Commits the deferred writes.
        every_results: Flush once this many results are pending.
        every_seconds: Flush pending results once this long has passed since the last flush.
        clock: Monotonic clock in seconds; replaceable for tests.
    """

    def __init__(
        self,
        flush: Callable[[], None],
        *,
        every_results: int = FLUSH_EVERY_RESULTS,
        every_seconds: float = FLUSH_EVERY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Start the interval now, with nothing pending."""
        self._flush = flush
        self._every_results = every_results
        self.every_seconds = every_seconds
        self._clock = clock
        self._pending = 0
        self._last_flush = clock()
        self._retry_not_before = 0.0
        self._warned = False

    def note_result(self) -> None:
        """Record that one more result is waiting to be flushed."""
        self._pending += 1

    def flush_if_due(self) -> None:
        """Flush when the count or the interval says so, unless a failed flush is still cooling off."""
        now = self._clock()
        if now < self._retry_not_before:
            return
        interval_elapsed = now - self._last_flush >= self.every_seconds
        if self._pending >= self._every_results or (self._pending and interval_elapsed):
            self.flush()

    def flush(self) -> None:
        """Flush now if anything is pending; a failure is logged once and leaves the results pending."""
        if self._pending:
            try:
                self._flush()
            except (sqlite3.Error, OSError) as flush_error:
                self._note_failure(flush_error)
                return
            self._pending = 0
        self._last_flush = self._clock()

    def _note_failure(self, flush_error: Exception) -> None:
        self._retry_not_before = self._clock() + self.every_seconds
        if self._warned:
            logger.debug(
                'Cache flush failed again (%s: %s); the writes stay pending for the next flush',
                type(flush_error).__name__,
                flush_error,
            )
            return
        self._warned = True
        logger.warning(
            'Could not write finished gremlin results to the cache (%s: %s). '
            'The run continues, retries the writes at the next flush, and the cache retries them again when it '
            'closes. Further flush failures are logged at DEBUG.',
            type(flush_error).__name__,
            flush_error,
        )
