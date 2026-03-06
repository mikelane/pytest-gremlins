"""Tests for cache type definitions.

Validates that JsonValue and CachedGremlinResult are importable,
correctly structured, and usable at cache boundaries.
"""

import pytest

from pytest_gremlins.cache.types import (  # noqa: TC001
    CachedGremlinResult,
    JsonValue,
)


@pytest.mark.small
class DescribeCacheTypes:
    """Tests for cache type aliases and TypedDicts."""

    def it_exports_json_value_type_alias(self):
        """JsonValue TypeAlias is importable from cache.types."""
        value: JsonValue = 'hello'
        assert value == 'hello'

    def it_exports_cached_gremlin_result_typeddict(self):
        """CachedGremlinResult TypedDict is importable from cache.types."""
        result: CachedGremlinResult = {
            'status': 'zapped',
            'killing_test': 'test_foo',
            'execution_time_ms': 12.5,
        }

        assert result['status'] == 'zapped'
        assert result['killing_test'] == 'test_foo'
        assert result['execution_time_ms'] == 12.5

    def it_accepts_none_for_optional_fields(self):
        """CachedGremlinResult accepts None for killing_test and execution_time_ms."""
        result: CachedGremlinResult = {
            'status': 'survived',
            'killing_test': None,
            'execution_time_ms': None,
        }

        assert result['status'] == 'survived'
        assert result['killing_test'] is None
        assert result['execution_time_ms'] is None
