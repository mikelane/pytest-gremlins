"""Tests for xdist item ID capture via pytest_xdist_node_collection_finished.

When running with xdist the controller never calls pytest_collection_finish
on its own items (DSession skips collection).  Instead, each worker reports
its collected items via ``pytest_xdist_node_collection_finished``.

pytest-gremlins captures the first worker's item list and stores it on
GremlinSession so that pytest_sessionfinish can set up gremlins without a
real pytest collection on the controller.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _set_session,
    pytest_xdist_node_collection_finished,
)


@pytest.mark.small
class TestXdistItemIds:
    """GremlinSession stores xdist_item_ids after node collection finishes."""

    def test_session_has_xdist_item_ids_field(self) -> None:
        """GremlinSession dataclass has an xdist_item_ids field defaulting to empty list."""
        gs = GremlinSession()
        assert gs.xdist_item_ids == []

    def test_hook_stores_item_ids_from_first_worker(self) -> None:
        """Item IDs reported by the first worker are stored on the session."""
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()
        ids = ['tests/test_foo.py::test_a', 'tests/test_foo.py::test_b']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids == ids

    def test_hook_stores_different_ids_correctly(self) -> None:
        """Different item IDs are stored correctly - rules out hardcoding."""
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()
        ids = ['tests/test_bar.py::test_x', 'tests/test_bar.py::test_y', 'tests/test_bar.py::test_z']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids == ids

    def test_hook_does_not_overwrite_existing_ids(self) -> None:
        """Second worker call does not overwrite already-captured item IDs."""
        gs = GremlinSession(enabled=True)
        first_ids = ['tests/test_foo.py::test_a']
        gs.xdist_item_ids = list(first_ids)
        _set_session(gs)

        node = MagicMock()
        second_ids = ['tests/test_bar.py::test_b']

        pytest_xdist_node_collection_finished(node=node, ids=second_ids)

        assert gs.xdist_item_ids == first_ids

    def test_hook_skips_when_no_session(self) -> None:
        """Hook is a no-op when no GremlinSession is active."""
        _set_session(None)

        node = MagicMock()
        ids = ['tests/test_foo.py::test_a']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

    def test_hook_skips_when_session_disabled(self) -> None:
        """Hook is a no-op when GremlinSession is disabled."""
        gs = GremlinSession(enabled=False)
        _set_session(gs)

        node = MagicMock()
        ids = ['tests/test_foo.py::test_a']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids == []
