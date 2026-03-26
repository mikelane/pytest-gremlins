"""Type definitions for cache boundaries.

Provides ``JsonValue`` for generic JSON-serialisable data and
``CachedGremlinResult`` for the per-gremlin cache entry shape.
"""

from __future__ import annotations

from typing import (
    NotRequired,
    TypeAlias,
    TypedDict,
)

JsonValue: TypeAlias = str | int | float | bool | None | list['JsonValue'] | dict[str, 'JsonValue']


class CachedGremlinResult(TypedDict):
    """Shape of a per-gremlin result stored in the cache.

    Attributes:
        status: One of the ``GremlinResultStatus`` *values*
                (``'zapped'``, ``'survived'``, ``'timeout'``, ``'error'``).
        killing_test: Name of the test that killed the gremlin, or ``None``.
        execution_time_ms: Wall-clock milliseconds for the gremlin run, or ``None``.
        error_output: Captured stderr or exception text for errored gremlins.
    """

    status: str
    killing_test: str | None
    execution_time_ms: float | None
    error_output: NotRequired[str]
