"""Tests for the OperatorRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.operators.protocol import GremlinOperator
from pytest_gremlins.operators.registry import OperatorRegistry

if TYPE_CHECKING:
    import ast


@pytest.mark.small
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


@pytest.mark.small
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


@pytest.mark.small
class DescribeOperatorRegistry:
    """Test the OperatorRegistry class."""

    def it_register_adds_operator_to_registry(self):
        registry = OperatorRegistry()

        registry.register(FakeOperator)

        assert 'fake' in registry.available()

    def it_register_uses_explicit_name_when_provided(self):
        registry = OperatorRegistry()

        registry.register(FakeOperator, name='custom_name')

        assert 'custom_name' in registry.available()
        assert 'fake' not in registry.available()

    def it_returns_operator_instance(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)

        operator = registry.get('fake')

        assert isinstance(operator, FakeOperator)
        assert isinstance(operator, GremlinOperator)

    def it_raises_key_error_for_unknown_operator(self):
        registry = OperatorRegistry()

        with pytest.raises(KeyError, match='unknown'):
            registry.get('unknown')

    def it_returns_all_registered_operators(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all()

        assert len(operators) == 2
        names = [op.name for op in operators]
        assert 'fake' in names
        assert 'another_fake' in names

    def it_returns_only_specified_operators_when_enabled_filter_set(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all(enabled=['fake'])

        assert len(operators) == 1
        assert operators[0].name == 'fake'

    def it_preserves_enabled_order(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all(enabled=['another_fake', 'fake'])

        names = [op.name for op in operators]
        assert names == ['another_fake', 'fake']

    def it_ignores_unknown_operators_in_enabled_list(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)

        with pytest.warns(UserWarning, match="Unknown operator 'unknown' requested"):
            operators = registry.get_all(enabled=['fake', 'unknown'])

        assert len(operators) == 1
        assert operators[0].name == 'fake'

    def it_emits_warning_for_unknown_operators(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)

        with pytest.warns(UserWarning, match="Unknown operator 'unknown_op' requested"):
            registry.get_all(enabled=['fake', 'unknown_op'])

    def it_returns_list_of_registered_names(self):
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        available = registry.available()

        assert 'fake' in available
        assert 'another_fake' in available

    def it_returns_empty_available_from_empty_registry(self):
        registry = OperatorRegistry()

        assert registry.available() == []

    def it_register_overwrites_existing_operator_with_same_name(self) -> None:
        """Registering a second operator under the same name silently replaces the first."""
        registry = OperatorRegistry()

        class FirstOp:
            @property
            def name(self) -> str:
                return 'my_op'

            @property
            def description(self) -> str:
                return 'First op'

            def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
                return False

            def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
                return []

        class SecondOp:
            @property
            def name(self) -> str:
                return 'my_op'

            @property
            def description(self) -> str:
                return 'Second op'

            def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
                return False

            def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
                return []

        registry.register(FirstOp)
        registry.register(SecondOp)

        assert isinstance(registry.get('my_op'), SecondOp)

    def it_register_decorator_without_explicit_name_uses_operator_name_property(self) -> None:
        """@registry.register_decorator() with no arg uses the operator's .name property as the key."""
        registry = OperatorRegistry()

        @registry.register_decorator()
        class NamedOp:
            @property
            def name(self) -> str:
                return 'from_property'

            @property
            def description(self) -> str:
                return 'Uses name property'

            def can_mutate(self, node: ast.AST) -> bool:  # noqa: ARG002
                return False

            def mutate(self, node: ast.AST) -> list[ast.AST]:  # noqa: ARG002
                return []

        assert 'from_property' in registry.available()
        assert isinstance(registry.get('from_property'), NamedOp)

    def it_get_all_with_empty_enabled_list_returns_empty(self) -> None:
        """get_all(enabled=[]) returns []."""
        registry = OperatorRegistry()
        registry.register(FakeOperator)
        registry.register(AnotherFakeOperator)

        operators = registry.get_all(enabled=[])

        assert operators == []

    def it_register_as_decorator(self):
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
