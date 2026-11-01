"""Build cache payloads that are deliberately smaller than the full ``CachedGremlinResult`` shape.

Store and cache tests round-trip minimal payloads such as ``{'status': 'zapped'}`` to prove that whatever
was written is read back unchanged. The value is returned exactly as given; only its static type changes.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    cast,
)

if TYPE_CHECKING:
    from pytest_gremlins.cache.types import CachedGremlinResult


def partial_entry(**fields: object) -> CachedGremlinResult:
    return cast('CachedGremlinResult', dict(fields))
