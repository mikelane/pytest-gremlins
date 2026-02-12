"""Tests for the AST transformer that embeds mutations."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import (
    build_switching_expression,
    collect_gremlins,
    create_gremlins_for_node,
    generate_comparison_mutations,
    transform_source,
)
from pytest_gremlins.operators.comparison import ComparisonOperator


class TestMutationGenerator:
    """Test generating mutations for comparison operators."""

    def test_generate_mutations_for_less_than(self):
        source = 'x < 10'
        tree = ast.parse(source, mode='eval')
        compare_node = tree.body
        assert isinstance(compare_node, ast.Compare)

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
        assert isinstance(compare_node, ast.Compare)
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
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_stmt = func_def.body[0]
        assert isinstance(return_stmt, ast.Return)
        original_compare = return_stmt.value
        assert original_compare is not None

        switching_expr = build_switching_expression(original_compare, gremlins)

        assert isinstance(switching_expr, ast.IfExp)

    def test_switching_expression_executes_original_when_no_gremlin_active(self, monkeypatch):
        source = 'age >= 18'
        gremlins, tree = collect_gremlins(source, 'example.py')
        expr_stmt = tree.body[0]
        assert isinstance(expr_stmt, ast.Expr)
        original_compare = expr_stmt.value

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
        expr_stmt = tree.body[0]
        assert isinstance(expr_stmt, ast.Expr)
        original_compare = expr_stmt.value

        switching_expr = build_switching_expression(original_compare, gremlins)
        ast.fix_missing_locations(switching_expr)

        # Use the actual gremlin ID from the first gremlin (IDs are now file-prefixed)
        first_gremlin_id = gremlins[0].gremlin_id
        exec_globals = {'age': 18, '__gremlin_active__': first_gremlin_id}
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
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        function_body = func_def.body[0]
        assert isinstance(function_body, ast.If)

    def test_transformed_code_executes_correctly_with_no_gremlin(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        _, tree = transform_source(source, 'example.py')
        ast.fix_missing_locations(tree)

        code = compile(tree, 'example.py', 'exec')
        exec_globals: dict[str, object] = {'__gremlin_active__': None}
        # NOTE: Python's exec() builtin is used intentionally here to test AST-generated code
        # This is testing mutation testing infrastructure in a controlled test environment
        # Not using shell commands - this is Python code execution
        exec(code, exec_globals)  # noqa: S102

        is_adult = exec_globals['is_adult']
        assert callable(is_adult)
        assert is_adult(21) is True
        assert is_adult(18) is True
        assert is_adult(17) is False

    def test_transformed_code_executes_mutation_when_gremlin_active(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, tree = transform_source(source, 'example.py')
        ast.fix_missing_locations(tree)

        code = compile(tree, 'example.py', 'exec')
        exec_globals: dict[str, object] = {'__gremlin_active__': gremlins[0].gremlin_id}
        # NOTE: Python's exec() builtin is used intentionally here to test AST-generated code
        # This is testing mutation testing infrastructure in a controlled test environment
        exec(code, exec_globals)  # noqa: S102

        is_adult = exec_globals['is_adult']
        assert callable(is_adult)
        assert is_adult(18) is False


class TestMultiOperatorTransformer:
    """Test transformer with multiple operators."""

    def test_transform_source_generates_gremlins_for_arithmetic_operations(self):
        source = """
def calculate(x, y):
    return x + y
"""
        gremlins, _tree = transform_source(source, 'example.py')

        assert len(gremlins) >= 1
        assert any(g.operator_name == 'arithmetic' for g in gremlins)

    def test_transform_source_generates_gremlins_for_boolean_operations(self):
        source = """
def check(a, b):
    return a and b
"""
        gremlins, _tree = transform_source(source, 'example.py')

        assert len(gremlins) >= 1
        assert any(g.operator_name == 'boolean' for g in gremlins)

    def test_transform_source_generates_gremlins_for_boundary_conditions(self):
        source = """
def is_adult(age):
    return age >= 18
"""
        gremlins, _tree = transform_source(source, 'example.py')

        boundary_gremlins = [g for g in gremlins if g.operator_name == 'boundary']
        assert len(boundary_gremlins) >= 1

    def test_transform_source_generates_gremlins_for_return_statements(self):
        source = """
def get_value():
    return 42
"""
        gremlins, _tree = transform_source(source, 'example.py')

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
        gremlins, _tree = transform_source(source, 'example.py')

        operator_names = {g.operator_name for g in gremlins}
        assert 'comparison' in operator_names
        assert 'arithmetic' in operator_names
        assert 'boolean' in operator_names
        assert 'boundary' in operator_names
        assert 'return' in operator_names

    def test_transform_source_generates_gremlins_for_not_operator(self):
        source = """
def negate(x):
    return not x
"""
        gremlins, _tree = transform_source(source, 'example.py')

        assert any(g.operator_name == 'boolean' for g in gremlins)
        assert any('not' in g.description.lower() for g in gremlins)

    def test_transform_source_handles_return_true_false_mutations(self):
        source = """
def check():
    return True
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # True/False mutations come from boolean operator, not return
        boolean_gremlins = [g for g in gremlins if g.operator_name == 'boolean']
        assert any('True' in g.description or 'False' in g.description for g in boolean_gremlins)

    def test_transform_source_handles_unsupported_binop(self):
        source = """
def bitwise(x, y):
    return x & y
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # BitAnd is not a supported arithmetic operator
        # But return mutation should still work
        return_gremlins = [g for g in gremlins if g.operator_name == 'return']
        assert len(return_gremlins) >= 1

    def test_transform_source_handles_unsupported_boolop(self):
        source = """
def check(x):
    return x
"""
        # No boolean operations, just testing that visitor handles code without them
        gremlins, _tree = transform_source(source, 'example.py')
        # Should have at least return gremlins
        assert any(g.operator_name == 'return' for g in gremlins)


class TestTransformerEdgeCases:
    """Test edge cases in the transformer."""

    def test_transform_source_handles_bitwise_binop(self):
        """BitAnd is a BinOp but not mutated by arithmetic operator."""
        source = """
def bitwise(x, y):
    a = x & y
    return a
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # Should have return gremlins but no arithmetic for bitwise
        arithmetic_gremlins = [g for g in gremlins if g.operator_name == 'arithmetic']
        assert len(arithmetic_gremlins) == 0  # & is not an arithmetic operator

    def test_transform_source_handles_unary_minus(self):
        """Unary minus is a UnaryOp but not mutated by boolean operator."""
        source = """
def negate(x):
    return -x
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # Should have return gremlins but no boolean for unary minus
        boolean_gremlins = [g for g in gremlins if g.operator_name == 'boolean']
        assert len(boolean_gremlins) == 0  # -x is not a boolean operator

    def test_transform_source_handles_unsupported_comparison(self):
        """Is/IsNot comparisons are not mutated."""
        source = """
def check(x):
    return x is None
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # Is operator is not mutated by comparison operator
        comparison_gremlins = [g for g in gremlins if g.operator_name == 'comparison']
        assert len(comparison_gremlins) == 0

    def test_transform_source_handles_non_boolean_constant(self):
        """Non-boolean constants are not mutated by boolean operator."""
        source = """
def get_value():
    return 42
"""
        gremlins, _tree = transform_source(source, 'example.py')

        # 42 is not a boolean constant
        boolean_gremlins = [g for g in gremlins if g.operator_name == 'boolean']
        assert len(boolean_gremlins) == 0


class TestCreateGremlinsForNode:
    """Test create_gremlins_for_node function directly."""

    def test_returns_empty_list_when_operator_cannot_mutate_node(self):
        """Returns empty list when operator.can_mutate returns False."""
        # BinOp node that ComparisonOperator cannot mutate
        node = ast.parse('x + 10', mode='eval').body
        assert isinstance(node, ast.BinOp)

        operator = ComparisonOperator()
        counter = [0]

        def id_gen():
            counter[0] += 1
            return f'g{counter[0]:03d}'

        gremlins = create_gremlins_for_node(node, operator, 'test.py', id_gen)

        assert gremlins == []
        assert counter[0] == 0  # No IDs were generated


class TestGremlinIdUniquenessAcrossFiles:
    """Test that gremlin IDs are globally unique across different files."""

    def test_gremlins_from_different_files_have_disjoint_ids(self):
        source = 'x = 1 + 2'
        gremlins_a, _ = transform_source(source, 'file_a.py')
        gremlins_b, _ = transform_source(source, 'file_b.py')

        ids_a = {g.gremlin_id for g in gremlins_a}
        ids_b = {g.gremlin_id for g in gremlins_b}

        assert ids_a.isdisjoint(ids_b)

    def test_same_named_files_in_different_directories_have_disjoint_ids(self):
        source = 'x = 1 + 2'
        gremlins_src, _ = transform_source(source, 'src/utils.py')
        gremlins_tests, _ = transform_source(source, 'tests/utils.py')

        ids_src = {g.gremlin_id for g in gremlins_src}
        ids_tests = {g.gremlin_id for g in gremlins_tests}

        assert ids_src.isdisjoint(ids_tests)

    def test_gremlin_ids_contain_file_stem_prefix(self):
        source = 'x = 1 + 2'
        gremlins, _ = transform_source(source, 'my_module.py')

        assert len(gremlins) >= 1
        assert all('my_module' in g.gremlin_id for g in gremlins)
