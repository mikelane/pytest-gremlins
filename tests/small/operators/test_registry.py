"""Tests for the OperatorRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.operators.protocol import GremlinOperator
from pytest_gremlins.operators.registry import OperatorRegistry


if TYPE_CHECKING:
    import ast


class FakeOperator:
    """A fake operator for testing the registry."""

    @property
    def name(self) -> str:
        return 'fake'

    @property
    def description(self) -> str:
        return 'A fake operator for testing'

    def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
        return False

    def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
        return []


class AnotherFakeOperator:
    """Another fake operator for testing."""

    @property
    def name(self) -> str:
        return 'another_fake'

    @property
    def description(self) -> str:
        return 'Another fake operator'

    def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
        return False

    def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
        return []


class TestOperatorRegistry:
    """Test the OperatorRegistry class."""

    def test_register_adds_operator_to_registry(self):
        registry = OperatorRegistry()

        registry.register(FakeOperator)

        assert 'fake' in registry.available()

    def test_register_uses_explicit_name_when_provided(self):
        registry = OperatorRegistry()

        registry.register(FakeOperator, name='custom_name')

        assert 'custom_name' in registry.available()
        assert 'fake' not in registry.available()

    def test_get_returns_operator_instance(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)

        operator = registry.get('fake')

        assert isinstance(operator, FakeOperator)
        assert isinstance(operator, GremlinOperator)

    def test_get_raises_key_error_for_unknown_operator(self):
        registry = OperatorRegistry()

        with pytest.raises(KeyError, match='unknown'):
            registry.get('unknown')

    def test_get_all_returns_all_registered_operators(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all()

        assert len(operators) == 2
        names = [op.name for op in operators]
        assert 'fake' in names
        assert 'another_fake' in names

    def test_get_all_with_enabled_filter_returns_only_specified_operators(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all(enabled=['fake'])

        assert len(operators) == 1
        assert operators[0].name == 'fake'

    def test_get_all_preserves_enabled_order(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all(enabled=['another_fake', 'fake'])

        names = [op.name for op in operators]
        assert names == ['another_fake', 'fake']

    def test_get_all_ignores_unknown_operators_in_enabled(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)

        operators = registry.get_all(enabled=['fake', 'unknown'])

        assert len(operators) == 1
        assert operators[0].name == 'fake'

    def test_available_returns_list_of_registered_names(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        available = registry.available()

        assert 'fake' in available
        assert 'another_fake' in available

    def test_empty_registry_returns_empty_available(self):
        registry = OperatorRegistry()

        assert registry.available() == []

    def test_register_as_decorator(self):
        registry = OperatorRegistry()

        @registry.register_decorator('decorated')
        class DecoratedOperator:
            @property
            def name(self) -> str:
                return 'decorated'

            @property
            def description(self) -> str:
                return 'Decorated operator'

            def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
                return False

            def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
                return []

        assert 'decorated' in registry.available()
        assert isinstance(registry.get('decorated'), DecoratedOperator)
