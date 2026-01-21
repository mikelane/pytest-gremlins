"""Tests for the ArithmeticOperator."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.operators.arithmetic import ArithmeticOperator
from pytest_gremlins.operators.protocol import GremlinOperator


class TestArithmeticOperatorProtocol:
    """Test that ArithmeticOperator implements the GremlinOperator protocol."""

    def test_implements_gremlin_operator_protocol(self):
        operator = ArithmeticOperator()
        assert isinstance(operator, GremlinOperator)

    def test_name_is_arithmetic(self):
        operator = ArithmeticOperator()
        assert operator.name == 'arithmetic'

    def test_description_describes_the_operator(self):
        operator = ArithmeticOperator()
        assert 'arithmetic' in operator.description.lower()


class TestArithmeticOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_binop_add(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is True

    @pytest.mark.parametrize(
        'source',
        [
            'x + y',
            'x - y',
            'x * y',
            'x / y',
            'x // y',
            'x % y',
            'x ** y',
        ],
    )
    def test_returns_true_for_all_supported_operations(self, source):
        operator = ArithmeticOperator()
        node = ast.parse(source, mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_false_for_comparison_node(self):
        operator = ArithmeticOperator()
        node = ast.parse('x < 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_bitwise_operations(self):
        operator = ArithmeticOperator()
        node = ast.parse('x & y', mode='eval').body

        assert operator.can_mutate(node) is False


class TestArithmeticOperatorMutate:
    """Test the mutate method."""

    def test_add_generates_one_mutation(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1

    def test_add_mutates_to_subtract(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert isinstance(mutations[0].op, ast.Sub)

    @pytest.mark.parametrize(
        ('source', 'expected_ops'),
        [
            ('x + y', [ast.Sub]),
            ('x - y', [ast.Add]),
            ('x * y', [ast.Div]),
            ('x / y', [ast.Mult]),
            ('x // y', [ast.Div]),
            ('x % y', [ast.FloorDiv]),
            ('x ** y', [ast.Mult]),
        ],
    )
    def test_all_arithmetic_mutations(self, source, expected_ops):
        operator = ArithmeticOperator()
        node = ast.parse(source, mode='eval').body

        mutations = operator.mutate(node)

        actual_ops = [type(m.op) for m in mutations]
        assert actual_ops == expected_ops

    def test_original_node_is_not_modified(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body
        original_op_type = type(node.op)

        operator.mutate(node)

        assert isinstance(node.op, original_op_type)

    def test_returns_empty_list_for_unsupported_node(self):
        operator = ArithmeticOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []


class TestArithmeticOperatorSymbols:
    """Test the operator symbol mapping."""

    def test_get_symbol_for_all_supported_ops(self):
        operator = ArithmeticOperator()

        assert operator.get_symbol(ast.Add()) == '+'
        assert operator.get_symbol(ast.Sub()) == '-'
        assert operator.get_symbol(ast.Mult()) == '*'
        assert operator.get_symbol(ast.Div()) == '/'
        assert operator.get_symbol(ast.FloorDiv()) == '//'
        assert operator.get_symbol(ast.Mod()) == '%'
        assert operator.get_symbol(ast.Pow()) == '**'

    def test_get_symbol_returns_question_mark_for_unknown_op(self):
        operator = ArithmeticOperator()

        assert operator.get_symbol(ast.BitAnd()) == '?'
