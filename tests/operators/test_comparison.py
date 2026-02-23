"""Tests for the ComparisonOperator."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.operators.comparison import ComparisonOperator
from pytest_gremlins.operators.protocol import GremlinOperator


@pytest.mark.small
class DescribeComparisonOperatorProtocol:
    """Test that ComparisonOperator implements the GremlinOperator protocol."""

    def it_implements_gremlin_operator_protocol(self):
        operator = ComparisonOperator()
        assert isinstance(operator, GremlinOperator)

    def it_name_is_comparison(self):
        operator = ComparisonOperator()
        assert operator.name == 'comparison'

    def it_description_describes_the_operator(self):
        operator = ComparisonOperator()
        assert 'comparison' in operator.description.lower()


@pytest.mark.small
class DescribeComparisonOperatorCanMutate:
    """Test the can_mutate method."""

    def it_returns_true_for_compare_node_with_less_than(self):
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
    def it_returns_true_for_all_supported_comparisons(self, source):
        operator = ComparisonOperator()
        node = ast.parse(source, mode='eval').body

        assert operator.can_mutate(node) is True

    def it_returns_false_for_non_compare_node(self):
        operator = ComparisonOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False

    def it_returns_false_for_unsupported_comparison_is(self):
        operator = ComparisonOperator()
        node = ast.parse('x is None', mode='eval').body

        assert operator.can_mutate(node) is False

    def it_returns_false_for_unsupported_comparison_in(self):
        operator = ComparisonOperator()
        node = ast.parse('x in items', mode='eval').body

        assert operator.can_mutate(node) is False


@pytest.mark.small
class DescribeComparisonOperatorMutate:
    """Test the mutate method."""

    def it_less_than_generates_two_mutations(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 2

    def it_less_than_mutates_to_less_than_or_equal_and_greater_than(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body

        mutations = operator.mutate(node)

        mutation_ops = []
        for m in mutations:
            assert isinstance(m, ast.Compare)
            mutation_ops.append(m.ops[0].__class__.__name__)
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
    def it_generates_all_comparison_mutations(self, source, expected_ops):
        operator = ComparisonOperator()
        node = ast.parse(source, mode='eval').body

        mutations = operator.mutate(node)

        actual_ops = []
        for m in mutations:
            assert isinstance(m, ast.Compare)
            actual_ops.append(m.ops[0].__class__.__name__)
        assert sorted(actual_ops) == sorted(expected_ops)

    def it_does_not_modify_the_original_node(self):
        operator = ComparisonOperator()
        node = ast.parse('x < 10', mode='eval').body
        assert isinstance(node, ast.Compare)
        original_op_type = type(node.ops[0])

        operator.mutate(node)

        assert isinstance(node.ops[0], original_op_type)

    def it_returns_empty_list_for_unsupported_node(self):
        operator = ComparisonOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def it_chained_comparison_generates_mutations_for_each_operator(self):
        operator = ComparisonOperator()
        node = ast.parse('0 < x < 10', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 4

    def it_mutate_skips_unsupported_operators_in_chain(self):
        operator = ComparisonOperator()
        # x is None has an Is operator which we don't mutate
        # But we construct a chained comparison with both < and is
        # by manually creating the AST
        node = ast.Compare(
            left=ast.Name(id='x', ctx=ast.Load()),
            ops=[ast.Lt(), ast.Is()],
            comparators=[
                ast.Constant(value=10),
                ast.Constant(value=None),
            ],
        )

        mutations = operator.mutate(node)

        # Only 2 mutations for the < operator (LtE and Gt)
        # The Is operator is skipped
        assert len(mutations) == 2


@pytest.mark.small
class DescribeComparisonOperatorSymbols:
    """Test the operator symbol mapping."""

    def it_returns_symbol_for_all_supported_ops(self):
        operator = ComparisonOperator()

        assert operator.get_symbol(ast.Lt()) == '<'
        assert operator.get_symbol(ast.LtE()) == '<='
        assert operator.get_symbol(ast.Gt()) == '>'
        assert operator.get_symbol(ast.GtE()) == '>='
        assert operator.get_symbol(ast.Eq()) == '=='
        assert operator.get_symbol(ast.NotEq()) == '!='

    def it_returns_question_mark_for_unknown_op(self):
        operator = ComparisonOperator()

        assert operator.get_symbol(ast.Is()) == '?'
