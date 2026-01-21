"""Tests for the GremlinOperator protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_gremlins.operators.protocol import GremlinOperator


if TYPE_CHECKING:
    import ast


class TestGremlinOperatorProtocol:
    """Test the GremlinOperator protocol interface."""

    def test_protocol_defines_name_property(self):
        assert hasattr(GremlinOperator, 'name')

    def test_protocol_defines_description_property(self):
        assert hasattr(GremlinOperator, 'description')

    def test_protocol_defines_can_mutate_method(self):
        assert hasattr(GremlinOperator, 'can_mutate')

    def test_protocol_defines_mutate_method(self):
        assert hasattr(GremlinOperator, 'mutate')

    def test_protocol_is_runtime_checkable(self):
        class DummyOperator:
            @property
            def name(self) -> str:
                return 'dummy'

            @property
            def description(self) -> str:
                return 'A dummy operator'

            def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
                return False

            def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
                return []

        assert isinstance(DummyOperator(), GremlinOperator)
