"""Tests for the mutation point finder."""

from __future__ import annotations

import ast

from pytest_gremlins.instrumentation.finder import find_mutation_points


class TestMutationPointFinder:
    """Test finding mutation points in AST."""

    def test_find_comparison_operators_in_simple_expression(self):
        source = 'x < 10'
        tree = ast.parse(source, mode='eval')

        points = find_mutation_points(tree)

        assert len(points) == 1
        assert isinstance(points[0], ast.Compare)

    def test_find_multiple_comparison_operators(self):
        source = """
def check(x, y):
    return x < 10 and y > 5
"""
        tree = ast.parse(source)

        points = find_mutation_points(tree)

        assert len(points) == 2

    def test_find_no_mutation_points_in_simple_assignment(self):
        source = 'x = 10'
        tree = ast.parse(source)

        points = find_mutation_points(tree)

        assert len(points) == 0

    def test_find_comparison_in_function_body(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        tree = ast.parse(source)

        points = find_mutation_points(tree)

        assert len(points) == 1
        compare_node = points[0]
        assert isinstance(compare_node, ast.Compare)
        assert isinstance(compare_node.ops[0], ast.GtE)
