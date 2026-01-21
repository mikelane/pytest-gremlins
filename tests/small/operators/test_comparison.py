"""Tests for the ComparisonOperator."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.operators.comparison import ComparisonOperator
from pytest_gremlins.operators.protocol import GremlinOperator


class TestComparisonOperatorProtocol:
    """Test that ComparisonOperator implements the GremlinOperator protocol."""

    def test_implements_gremlin_operator_protocol(self):
        operator = ComparisonOperator()
        assert isinstance(operator, GremlinOperator)

    def test_name_is_comparison(self):
        operator = ComparisonOperator()
        assert operator.name == 'comparison'

    def test_description_describes_the_operator(self):
        operator = ComparisonOperator()
        assert 'comparison' in operator.description.lower()


class TestComparisonOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_compare_node_with_less_than(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body

        assert operator.can_mutate(node) is True

    @pytest.mark.parametrize(
        'source',
        [
            'x < 10',
            'x <= 10',
            'x > 10',
            'x >= 10',
            'x == 10',
            'x != 10',
        ],
    )
    def test_returns_true_for_all_supported_comparisons(self, source):
        operator = ComparisonOperator()
        node = ast.parse(source, mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_false_for_non_compare_node(self):
        operator = ComparisonOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_unsupported_comparison_is(self):
        operator = ComparisonOperator()
        node = ast.parse('x is None', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_unsupported_comparison_in(self):
        operator = ComparisonOperator()
        node = ast.parse('x in items', mode='eval').body

        assert operator.can_mutate(node) is False


class TestComparisonOperatorMutate:
    """Test the mutate method."""

    def test_less_than_generates_two_mutations(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 2

    def test_less_than_mutates_to_less_than_or_equal_and_greater_than(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        mutation_ops = [m.ops[0].__class__.__name__ for m in mutations]
        assert 'LtE' in mutation_ops
        assert 'Gt' in mutation_ops

    @pytest.mark.parametrize(
        ('source', 'expected_ops'),
        [
            ('x < 10', ['LtE', 'Gt']),
            ('x <= 10', ['Lt', 'Gt']),
            ('x > 10', ['GtE', 'Lt']),
            ('x >= 10', ['Gt', 'Lt']),
            ('x == 10', ['NotEq']),
            ('x != 10', ['Eq']),
        ],
    )
    def test_all_comparison_mutations(self, source, expected_ops):
        operator = ComparisonOperator()
        node = ast.parse(source, mode='eval').body

        mutations = operator.mutate(node)

        actual_ops = [m.ops[0].__class__.__name__ for m in mutations]
        assert sorted(actual_ops) == sorted(expected_ops)

    def test_original_node_is_not_modified(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body
        original_op_type = type(node.ops[0])

        operator.mutate(node)

        assert isinstance(node.ops[0], original_op_type)

    def test_returns_empty_list_for_unsupported_node(self):
        operator = ComparisonOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def test_chained_comparison_generates_mutations_for_each_operator(self):
        operator = ComparisonOperator()
        node = ast.parse('0 < x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 4


class TestComparisonOperatorSymbols:
    """Test the operator symbol mapping."""

    def test_get_symbol_for_all_supported_ops(self):
        operator = ComparisonOperator()

        assert operator.get_symbol(ast.Lt()) == '<'
        assert operator.get_symbol(ast.LtE()) == '<='
        assert operator.get_symbol(ast.Gt()) == '>'
        assert operator.get_symbol(ast.GtE()) == '>='
        assert operator.get_symbol(ast.Eq()) == '=='
        assert operator.get_symbol(ast.NotEq()) == '!='

    def test_get_symbol_returns_question_mark_for_unknown_op(self):
        operator = ComparisonOperator()

        assert operator.get_symbol(ast.Is()) == '?'
