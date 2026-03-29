"""Tests for the reverse index that maps bare function names to full node IDs.

The reverse index replaces the linear suffix-match fallback in
_build_test_hashes_for_gremlin with O(1) lookups.
"""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _build_test_hashes_for_gremlin,
)


@pytest.mark.small
class DescribeTestNameToNodeIds:
    """Tests for the test_name_to_node_ids reverse index on GremlinSession."""

    def it_defaults_to_empty_dict(self) -> None:
        """A fresh GremlinSession has an empty reverse index."""
        gs = GremlinSession(enabled=True)

        assert gs.test_name_to_node_ids == {}


@pytest.mark.small
class DescribeBuildTestHashesWithReverseIndex:
    """Tests for _build_test_hashes_for_gremlin using the reverse index."""

    def it_resolves_bare_function_name_via_reverse_index(self) -> None:
        """A bare coverage name like 'test_bar' resolves via reverse index."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={
                'tests/test_foo.py::test_bar': 'tests/test_foo.py::test_bar',
            },
            test_hashes={'tests/test_foo.py': 'hash_abc'},
            test_name_to_node_ids={
                'test_bar': ['tests/test_foo.py::test_bar'],
            },
        )

        result = _build_test_hashes_for_gremlin(['test_bar'], gs)

        assert 'test_bar' in result
        assert result['test_bar'] == 'hash_abc'
