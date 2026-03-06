"""Cache module for incremental analysis.

Provides content hashing and result caching to skip unchanged code/tests
on subsequent runs.
"""

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore
from pytest_gremlins.cache.types import (
    CachedGremlinResult,
    JsonValue,
)

__all__ = ['CachedGremlinResult', 'ContentHasher', 'IncrementalCache', 'JsonValue', 'ResultStore']
