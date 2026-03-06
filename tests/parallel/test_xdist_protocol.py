"""Tests for the _XdistWorkerNode Protocol used in pytest_configure_node."""

from __future__ import annotations

import typing

import pytest

from pytest_gremlins.plugin import _XdistWorkerNode


@pytest.mark.small
class DescribeXdistWorkerNodeProtocol:
    """Tests for the _XdistWorkerNode Protocol."""

    def it_is_a_protocol(self) -> None:
        """_XdistWorkerNode is a typing.Protocol."""
        assert issubclass(_XdistWorkerNode, typing.Protocol)

    def it_accepts_object_with_workerinput_dict(self) -> None:
        """An object with workerinput dict[str, object] satisfies the protocol."""

        class FakeNode:
            workerinput: dict[str, object]

            def __init__(self) -> None:
                self.workerinput = {}

        node: _XdistWorkerNode = FakeNode()  # type: ignore[assignment]
        node.workerinput['gremlin_active'] = False
        assert node.workerinput['gremlin_active'] is False

    def it_exposes_workerinput_attribute(self) -> None:
        """_XdistWorkerNode Protocol declares workerinput as a required attribute."""
        hints = typing.get_type_hints(_XdistWorkerNode)
        assert 'workerinput' in hints
