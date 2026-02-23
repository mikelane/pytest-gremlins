"""Tests for the ArithmeticOperator."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.operators.arithmetic import ArithmeticOperator
from pytest_gremlins.operators.protocol import GremlinOperator


@pytest.mark.small
class DescribeArithmeticOperatorProtocol:
    """Test that ArithmeticOperator implements the GremlinOperator protocol."""

    def it_implements_gremlin_operator_protocol(self):
        operator = ArithmeticOperator()
        assert isinstance(operator, GremlinOperator)

    def it_name_is_arithmetic(self):
        operator = ArithmeticOperator()
        assert operator.name == 'arithmetic'

    def it_description_describes_the_operator(self):
        operator = ArithmeticOperator()
        assert 'arithmetic' in operator.description.lower()


@pytest.mark.small
class DescribeArithmeticOperatorCanMutate:
    """Test the can_mutate method."""

    def it_returns_true_for_binop_add(self):
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
    def it_returns_true_for_all_supported_operations(self, source):
        operator = ArithmeticOperator()
        node = ast.parse(source, mode='eval').body

        assert operator.can_mutate(node) is True

    def it_returns_false_for_comparison_node(self):
        operator = ArithmeticOperator()
        node = ast.parse('x < 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def it_returns_false_for_bitwise_operations(self):
        operator = ArithmeticOperator()
        node = ast.parse('x & y', mode='eval').body

        assert operator.can_mutate(node) is False


@pytest.mark.small
class DescribeArithmeticOperatorMutate:
    """Test the mutate method."""

    def it_generates_one_mutation_for_add(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1

    def it_mutates_add_to_subtract(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        mutation = mutations[0]
        assert isinstance(mutation, ast.BinOp)
        assert isinstance(mutation.op, ast.Sub)

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
    def it_generates_all_arithmetic_mutations(self, source, expected_ops):
        operator = ArithmeticOperator()
        node = ast.parse(source, mode='eval').body

        mutations = operator.mutate(node)

        actual_ops = []
        for m in mutations:
            assert isinstance(m, ast.BinOp)
            actual_ops.append(type(m.op))
        assert actual_ops == expected_ops

    def it_does_not_modify_the_original_node(self):
        operator = ArithmeticOperator()
        node = ast.parse('x + 10', mode='eval').body
        assert isinstance(node, ast.BinOp)
        original_op_type = type(node.op)

        operator.mutate(node)

        assert isinstance(node.op, original_op_type)

    def it_returns_empty_list_for_unsupported_node(self):
        operator = ArithmeticOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def it_returns_empty_list_for_binop_with_unsupported_operator(self):
        operator = ArithmeticOperator()
        # BitAnd (&) is a BinOp but not an arithmetic operator we mutate
        node = ast.parse('x & y', mode='eval').body
        assert isinstance(node, ast.BinOp)
        assert isinstance(node.op, ast.BitAnd)

        mutations = operator.mutate(node)

        assert mutations == []


@pytest.mark.small
class DescribeArithmeticOperatorSymbols:
    """Test the operator symbol mapping."""

    def it_returns_symbol_for_all_supported_ops(self):
        operator = ArithmeticOperator()

        assert operator.get_symbol(ast.Add()) == '+'
        assert operator.get_symbol(ast.Sub()) == '-'
        assert operator.get_symbol(ast.Mult()) == '*'
        assert operator.get_symbol(ast.Div()) == '/'
        assert operator.get_symbol(ast.FloorDiv()) == '//'
        assert operator.get_symbol(ast.Mod()) == '%'
        assert operator.get_symbol(ast.Pow()) == '**'

    def it_returns_question_mark_for_unknown_op(self):
        operator = ArithmeticOperator()

        assert operator.get_symbol(ast.BitAnd()) == '?'
