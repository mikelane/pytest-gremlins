"""Tests for the BoundaryOperator."""

from __future__ import annotations

import ast

from pytest_gremlins.operators.boundary import BoundaryOperator
from pytest_gremlins.operators.protocol import GremlinOperator


class TestBoundaryOperatorProtocol:
    """Test that BoundaryOperator implements the GremlinOperator protocol."""

    def test_implements_gremlin_operator_protocol(self):
        operator = BoundaryOperator()
        assert isinstance(operator, GremlinOperator)

    def test_name_is_boundary(self):
        operator = BoundaryOperator()
        assert operator.name == 'boundary'

    def test_description_describes_the_operator(self):
        operator = BoundaryOperator()
        assert 'boundary' in operator.description.lower()


class TestBoundaryOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_comparison_with_integer_literal(self):
        operator = BoundaryOperator()
        node = ast.parse('x >= 18', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_true_for_comparison_with_zero(self):
        operator = BoundaryOperator()
        node = ast.parse('len(s) > 0', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_false_for_comparison_with_non_integer(self):
        operator = BoundaryOperator()
        node = ast.parse('x < "hello"', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_comparison_without_constant(self):
        operator = BoundaryOperator()
        node = ast.parse('x < y', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_arithmetic_node(self):
        operator = BoundaryOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_float_constant(self):
        operator = BoundaryOperator()
        node = ast.parse('x < 3.14', mode='eval').body

        assert operator.can_mutate(node) is False


class TestBoundaryOperatorMutate:
    """Test the mutate method."""

    def test_integer_generates_two_mutations(self):
        operator = BoundaryOperator()
        node = ast.parse('x >= 18', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 2

    def test_mutates_to_plus_one_and_minus_one(self):
        operator = BoundaryOperator()
        node = ast.parse('x >= 18', mode='eval').body

        mutations = operator.mutate(node)

        values = [m.comparators[0].value for m in mutations]
        assert 17 in values
        assert 19 in values

    def test_mutates_zero_to_minus_one_and_one(self):
        operator = BoundaryOperator()
        node = ast.parse('x > 0', mode='eval').body

        mutations = operator.mutate(node)

        values = [m.comparators[0].value for m in mutations]
        assert -1 in values
        assert 1 in values

    def test_original_node_is_not_modified(self):
        operator = BoundaryOperator()
        node = ast.parse('x >= 18', mode='eval').body
        original_value = node.comparators[0].value

        operator.mutate(node)

        assert node.comparators[0].value == original_value

    def test_returns_empty_list_for_unsupported_node(self):
        operator = BoundaryOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def test_mutates_left_side_integer_constant(self):
        operator = BoundaryOperator()
        node = ast.parse('18 <= x', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 2
        values = [m.left.value for m in mutations]
        assert 17 in values
        assert 19 in values
