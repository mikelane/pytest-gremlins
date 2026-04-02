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
class DescribeXdistItemIds:
    """GremlinSession stores xdist_item_ids after node collection finishes."""

    def it_session_has_xdist_item_ids_field(self) -> None:
        """GremlinSession dataclass has an xdist_item_ids field defaulting to None (not yet set)."""
        gs = GremlinSession()
        assert gs.xdist_item_ids is None

    def it_hook_stores_item_ids_from_first_worker(self) -> None:
        """Item IDs reported by the first worker are stored on the session."""
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        ids = ['tests/test_foo.py::test_a', 'tests/test_foo.py::test_b']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids == ids

    def it_hook_stores_different_ids_ruling_out_hardcoding(self) -> None:
        """Different item IDs are stored on session - rules out hardcoding."""
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        ids = ['tests/test_bar.py::test_x', 'tests/test_bar.py::test_y', 'tests/test_bar.py::test_z']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids == ids

    def it_hook_does_not_overwrite_existing_ids(self) -> None:
        """Second worker call does not overwrite already-captured item IDs."""
        gs = GremlinSession(enabled=True)
        first_ids = ['tests/test_foo.py::test_a']
        gs.xdist_item_ids = list(first_ids)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        second_ids = ['tests/test_bar.py::test_b']

        pytest_xdist_node_collection_finished(node=node, ids=second_ids)

        assert gs.xdist_item_ids == first_ids

    def it_hook_skips_when_no_session(self) -> None:
        """Hook is a no-op when no GremlinSession is active."""
        _set_session(None)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        ids = ['tests/test_foo.py::test_a']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

    def it_hook_skips_when_session_disabled(self) -> None:
        """Hook is a no-op when GremlinSession is disabled."""
        gs = GremlinSession(enabled=False)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        ids = ['tests/test_foo.py::test_a']

        pytest_xdist_node_collection_finished(node=node, ids=ids)

        assert gs.xdist_item_ids is None

    def it_first_worker_reporting_empty_ids_stores_empty_list(self) -> None:
        """First worker with zero collected items stores an empty list.

        Calling the hook when xdist_item_ids is still the default [] stores
        the reported empty list.  This must produce [] (not remain unset).
        """
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        pytest_xdist_node_collection_finished(node=node, ids=[])

        # After first call with empty ids, the session list must be [].
        # (It already was [], so this verifies the hook ran without error.)
        assert gs.xdist_item_ids == []

    def it_second_worker_does_not_overwrite_empty_ids_from_first_worker(self) -> None:
        """If the first worker reported empty ids, a second worker must not overwrite them.

        An empty list is falsy.  The guard ``if gremlin_session.xdist_item_ids``
        evaluates to False for [], so the second worker's call overwrites the
        first worker's already-stored empty list — that is the bug.
        """
        gs = GremlinSession(enabled=True)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok

        # First worker reports empty collection
        pytest_xdist_node_collection_finished(node=node, ids=[])
        assert gs.xdist_item_ids == []

        # Second worker reports real items — must NOT overwrite first worker's []
        second_ids = ['tests/test_bar.py::test_b']
        pytest_xdist_node_collection_finished(node=node, ids=second_ids)

        # Bug: the guard uses truthiness so [] is falsy and second_ids replaces it
        assert gs.xdist_item_ids == []
