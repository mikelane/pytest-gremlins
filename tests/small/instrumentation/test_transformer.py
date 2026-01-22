"""Tests for the AST transformer that embeds mutations."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import (
    build_switching_expression,
    collect_gremlins,
    generate_comparison_mutations,
    transform_source,
)


class TestMutationGenerator:
    """Test generating mutations for comparison operators."""

    def test_generate_mutations_for_less_than(self):
        source = 'x < 10'
        tree = ast.parse(source, mode='eval')
        compare_node = tree.body

        mutations = generate_comparison_mutations(compare_node)

        assert len(mutations) == 2
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
    def test_generate_mutations_for_comparison_operators(self, source, expected_ops):
        tree = ast.parse(source, mode='eval')
        compare_node = tree.body

        mutations = generate_comparison_mutations(compare_node)

        actual_ops = [m.ops[0].__class__.__name__ for m in mutations]
        assert sorted(actual_ops) == sorted(expected_ops)

    def test_original_node_is_not_modified(self):
        source = 'x < 10'
        tree = ast.parse(source, mode='eval')
        compare_node = tree.body
        original_op_type = type(compare_node.ops[0])

        generate_comparison_mutations(compare_node)

        assert isinstance(compare_node.ops[0], original_op_type)


class TestCollectGremlins:
    """Test collecting gremlins from source code."""

    def test_collect_gremlins_returns_gremlins(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, _ = collect_gremlins(source, 'example.py')

        assert len(gremlins) == 2
        assert all(g.file_path == 'example.py' for g in gremlins)
        assert all(g.operator_name == 'comparison' for g in gremlins)

    def test_collect_gremlins_returns_original_ast(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        _, tree = collect_gremlins(source, 'example.py')

        assert tree is not None
        assert isinstance(tree, ast.Module)


class TestBuildSwitchingCode:
    """Test building AST code that implements mutation switching."""

    def test_build_switching_expression_returns_if_expression(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, tree = collect_gremlins(source, 'example.py')
        original_compare = tree.body[0].body[0].value

        switching_expr = build_switching_expression(original_compare, gremlins)

        assert isinstance(switching_expr, ast.IfExp)

    def test_switching_expression_executes_original_when_no_gremlin_active(self, monkeypatch):
        source = 'age >= 18'
        gremlins, tree = collect_gremlins(source, 'example.py')
        original_compare = tree.body[0].value

        switching_expr = build_switching_expression(original_compare, gremlins)
        ast.fix_missing_locations(switching_expr)

        monkeypatch.delenv('ACTIVE_GREMLIN', raising=False)
        exec_globals = {'age': 21, '__gremlin_active__': None}
        # NOTE: eval is used intentionally here to test AST-generated code
        # This is a test for mutation testing infrastructure, not arbitrary user input
        result = eval(compile(ast.Expression(switching_expr), '<test>', 'eval'), exec_globals)  # noqa: S307

        assert result is True

    def test_switching_expression_executes_mutation_when_gremlin_active(self):
        source = 'age >= 18'
        gremlins, tree = collect_gremlins(source, 'example.py')
        original_compare = tree.body[0].value

        switching_expr = build_switching_expression(original_compare, gremlins)
        ast.fix_missing_locations(switching_expr)

        exec_globals = {'age': 18, '__gremlin_active__': 'g001'}
        # NOTE: eval is used intentionally here to test AST-generated code
        # This is a test for mutation testing infrastructure, not arbitrary user input
        result = eval(compile(ast.Expression(switching_expr), '<test>', 'eval'), exec_globals)  # noqa: S307

        assert result is False


class TestMutationSwitchingTransformer:
    """Test the full AST transformer that embeds mutation switching."""

    def test_transform_source_replaces_comparisons_with_switches(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, tree = transform_source(source, 'example.py')

        # Now uses all 5 operators: 2 comparison + 2 boundary + 1 return = 5 gremlins
        assert len(gremlins) >= 2
        # The return statement is now wrapped in an If (for return mutation switching)
        function_body = tree.body[0].body[0]
        assert isinstance(function_body, ast.If)

    def test_transformed_code_executes_correctly_with_no_gremlin(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        _, tree = transform_source(source, 'example.py')
        ast.fix_missing_locations(tree)

        code = compile(tree, 'example.py', 'exec')
        exec_globals = {'__gremlin_active__': None}
        # NOTE: Python's exec() builtin is used intentionally here to test AST-generated code
        # This is testing mutation testing infrastructure in a controlled test environment
        # Not using shell commands - this is Python code execution
        exec(code, exec_globals)  # noqa: S102

        assert exec_globals['is_adult'](21) is True
        assert exec_globals['is_adult'](18) is True
        assert exec_globals['is_adult'](17) is False

    def test_transformed_code_executes_mutation_when_gremlin_active(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, tree = transform_source(source, 'example.py')
        ast.fix_missing_locations(tree)

        code = compile(tree, 'example.py', 'exec')
        exec_globals = {'__gremlin_active__': gremlins[0].gremlin_id}
        # NOTE: Python's exec() builtin is used intentionally here to test AST-generated code
        # This is testing mutation testing infrastructure in a controlled test environment
        exec(code, exec_globals)  # noqa: S102

        assert exec_globals['is_adult'](18) is False


class TestMultiOperatorTransformer:
    """Test transformer with multiple operators."""

    def test_transform_source_generates_gremlins_for_arithmetic_operations(self):
        source = """
def calculate(x, y):
    return x + y
"""
        gremlins, tree = transform_source(source, 'example.py')

        assert len(gremlins) >= 1
        assert any(g.operator_name == 'arithmetic' for g in gremlins)

    def test_transform_source_generates_gremlins_for_boolean_operations(self):
        source = """
def check(a, b):
    return a and b
"""
        gremlins, tree = transform_source(source, 'example.py')

        assert len(gremlins) >= 1
        assert any(g.operator_name == 'boolean' for g in gremlins)

    def test_transform_source_generates_gremlins_for_boundary_conditions(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, tree = transform_source(source, 'example.py')

        boundary_gremlins = [g for g in gremlins if g.operator_name == 'boundary']
        assert len(boundary_gremlins) >= 1

    def test_transform_source_generates_gremlins_for_return_statements(self):
        source = """
def get_value():
    return 42
"""
        gremlins, tree = transform_source(source, 'example.py')

        assert len(gremlins) >= 1
        assert any(g.operator_name == 'return' for g in gremlins)

    def test_transform_source_uses_all_five_operators(self):
        source = """
def complex_function(x, y):
    if x >= 10:
        return x + y
    elif x > 0 and y > 0:
        return True
    return False
"""
        gremlins, tree = transform_source(source, 'example.py')

        operator_names = {g.operator_name for g in gremlins}
        assert 'comparison' in operator_names
        assert 'arithmetic' in operator_names
        assert 'boolean' in operator_names
        assert 'boundary' in operator_names
        assert 'return' in operator_names
