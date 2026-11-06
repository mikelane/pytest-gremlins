"""Tests for the reverse index that maps bare function names to full node IDs."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import GremlinSession


@pytest.mark.small
class DescribeTestNameToNodeIds:
    """Tests for the test_name_to_node_ids reverse index on GremlinSession."""

    def it_defaults_to_empty_dict(self) -> None:
        """A fresh GremlinSession has an empty reverse index."""
        gs = GremlinSession(enabled=True)

        assert gs.test_name_to_node_ids == {}
