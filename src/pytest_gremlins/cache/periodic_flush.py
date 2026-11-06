"""Flush policy that keeps cached results durable while a long run is still going (issue #974)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

FLUSH_EVERY_RESULTS = 25
"""Results that may wait in memory before a flush.

One flush is one SQLite transaction, a few milliseconds, while a gremlin takes seconds to run, so the
cost is far below 1% of a run. A kill that arrives between flushes loses at most this many results.
"""

FLUSH_EVERY_SECONDS = 5.0
"""Longest a result waits in memory before a flush.

Bounds the loss when gremlins finish slowly, and when the run stalls on a single stuck gremlin, which
is the case that motivated the policy.
"""


class PeriodicFlusher:
    """Calls ``flush`` after enough results or enough time, whichever comes first.

    The owner calls :meth:`note_result` after each deferred cache write and :meth:`flush_if_due` at least
    once per ``every_seconds``. Nothing here is thread-safe: call it from the thread that owns the cache
    connection.

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

    def note_result(self) -> None:
        """Record that one more result is waiting to be flushed."""
        self._pending += 1

    def flush_if_due(self) -> None:
        """Flush when the count or the interval says so."""
        interval_elapsed = self._clock() - self._last_flush >= self.every_seconds
        if self._pending >= self._every_results or (self._pending and interval_elapsed):
            self.flush()

    def flush(self) -> None:
        """Flush now if anything is pending."""
        if self._pending:
            self._flush()
            self._pending = 0
        self._last_flush = self._clock()
