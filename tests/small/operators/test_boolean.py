"""Tests for the BooleanOperator."""

from __future__ import annotations

import ast

from pytest_gremlins.operators.boolean import BooleanOperator
from pytest_gremlins.operators.protocol import GremlinOperator


class TestBooleanOperatorProtocol:
    """Test that BooleanOperator implements the GremlinOperator protocol."""

    def test_implements_gremlin_operator_protocol(self):
        operator = BooleanOperator()
        assert isinstance(operator, GremlinOperator)

    def test_name_is_boolean(self):
        operator = BooleanOperator()
        assert operator.name == 'boolean'

    def test_description_describes_the_operator(self):
        operator = BooleanOperator()
        assert 'boolean' in operator.description.lower()


class TestBooleanOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_boolop_and(self):
        operator = BooleanOperator()
        node = ast.parse('x and y', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_true_for_boolop_or(self):
        operator = BooleanOperator()
        node = ast.parse('x or y', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_true_for_unaryop_not(self):
        operator = BooleanOperator()
        node = ast.parse('not x', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_true_for_constant_true(self):
        operator = BooleanOperator()
        node = ast.parse('True', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_true_for_constant_false(self):
        operator = BooleanOperator()
        node = ast.parse('False', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_false_for_comparison_node(self):
        operator = BooleanOperator()
        node = ast.parse('x < 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_arithmetic_node(self):
        operator = BooleanOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_unaryop_negative(self):
        operator = BooleanOperator()
        node = ast.parse('-x', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_non_boolean_constant(self):
        operator = BooleanOperator()
        node = ast.parse('42', mode='eval').body

        assert operator.can_mutate(node) is False


class TestBooleanOperatorMutate:
    """Test the mutate method."""

    def test_and_mutates_to_or(self):
        operator = BooleanOperator()
        node = ast.parse('x and y', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        mutation = mutations[0]
        assert isinstance(mutation, ast.BoolOp)
        assert isinstance(mutation.op, ast.Or)

    def test_or_mutates_to_and(self):
        operator = BooleanOperator()
        node = ast.parse('x or y', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        mutation = mutations[0]
        assert isinstance(mutation, ast.BoolOp)
        assert isinstance(mutation.op, ast.And)

    def test_not_x_mutates_to_x(self):
        operator = BooleanOperator()
        node = ast.parse('not x', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Name)
        assert mutations[0].id == 'x'

    def test_true_mutates_to_false(self):
        operator = BooleanOperator()
        node = ast.parse('True', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Constant)
        assert mutations[0].value is False

    def test_false_mutates_to_true(self):
        operator = BooleanOperator()
        node = ast.parse('False', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Constant)
        assert mutations[0].value is True

    def test_original_node_is_not_modified(self):
        operator = BooleanOperator()
        node = ast.parse('x and y', mode='eval').body
        assert isinstance(node, ast.BoolOp)
        original_op_type = type(node.op)

        operator.mutate(node)

        assert isinstance(node.op, original_op_type)

    def test_returns_empty_list_for_unsupported_node(self):
        operator = BooleanOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []
