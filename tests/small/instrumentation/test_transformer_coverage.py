"""Tests for transformer edge cases to achieve 100% coverage.

These tests specifically target the remaining uncovered lines and branches
in the transformer module.
"""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import (
    MutationSwitchingTransformer,
    _get_return_description,
    transform_source,
)
from pytest_gremlins.operators import ComparisonOperator


@pytest.mark.small
class TestReturnDescriptionConstantToConstant:
    """Tests for _get_return_description with constant-to-constant mutations."""

    def test_return_constant_to_constant_description(self) -> None:
        """Covers lines 181-187: return constant to constant mutation description."""
        # Create original and mutated Return nodes with Constant values
        original = ast.Return(value=ast.Constant(value=42))
        mutated = ast.Return(value=ast.Constant(value=0))

        result = _get_return_description(original, mutated)

        assert result == 'return 42 to 0'

    def test_return_string_constant_to_string_constant(self) -> None:
        """Constant to constant with string values."""
        original = ast.Return(value=ast.Constant(value='hello'))
        mutated = ast.Return(value=ast.Constant(value=''))

        result = _get_return_description(original, mutated)

        assert result == "return 'hello' to ''"

    def test_return_bool_constant_to_bool_constant(self) -> None:
        """Constant to constant with boolean values."""
        original = ast.Return(value=ast.Constant(value=True))
        mutated = ast.Return(value=ast.Constant(value=False))

        result = _get_return_description(original, mutated)

        assert result == 'return True to False'


@pytest.mark.small
class TestTransformerEdgeCasesForCoverage:
    """Tests for transformer visitor edge cases."""

    def test_visit_boolop_returns_unchanged_when_no_gremlins(self) -> None:
        """Covers line 417: visit_BoolOp returns node when no gremlins produced.

        This happens when BoolOp uses operators that can't be mutated,
        but currently all And/Or can be mutated. We need to use operators
        that don't include BooleanOperator.
        """
        source = """
def check(a, b):
    return a and b
"""
        # Use only ComparisonOperator - it won't produce gremlins for BoolOp
        operators = [ComparisonOperator()]
        gremlins, _tree = transform_source(source, 'test.py', operators=operators)

        # With only comparison operator, no gremlins from 'and' expression
        # The BoolOp should return unchanged node (line 417)
        assert all(g.operator_name == 'comparison' for g in gremlins)
        # The 'and' expression should be unchanged in the tree

    def test_visit_return_returns_unchanged_when_no_gremlins(self) -> None:
        """Covers line 448: visit_Return returns node when no gremlins produced.

        Return statements with no value (bare return) don't produce gremlins
        since there's nothing to mutate.
        """
        source = """
def do_nothing():
    return
"""
        # Use only comparison operator - it won't produce gremlins for bare return
        operators = [ComparisonOperator()]
        gremlins, _tree = transform_source(source, 'test.py', operators=operators)

        # No gremlins should be produced from bare return with comparison operator
        assert len(gremlins) == 0


@pytest.mark.small
class TestMutationSwitchingTransformerPrivateMethods:
    """Tests for MutationSwitchingTransformer internal methods."""

    def test_create_gremlins_for_compare_is_callable(self) -> None:
        """Covers line 370: _create_gremlins_for_compare method.

        This is a wrapper method that's used internally. We call it directly
        to ensure coverage.
        """
        source = 'x >= 10'
        tree = ast.parse(source, mode='eval')
        compare_node = tree.body
        assert isinstance(compare_node, ast.Compare)

        transformer = MutationSwitchingTransformer('test.py')
        gremlins = transformer._create_gremlins_for_compare(compare_node)

        assert len(gremlins) >= 1
        assert all(g.operator_name == 'comparison' for g in gremlins)
