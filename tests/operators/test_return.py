"""Tests for the ReturnOperator."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.operators.protocol import GremlinOperator
from pytest_gremlins.operators.return_value import ReturnOperator


@pytest.mark.small
class DescribeReturnOperatorProtocol:
    """Test that ReturnOperator implements the GremlinOperator protocol."""

    def it_implements_gremlin_operator_protocol(self):
        operator = ReturnOperator()
        assert isinstance(operator, GremlinOperator)

    def it_name_is_return(self):
        operator = ReturnOperator()
        assert operator.name == 'return'

    def it_description_describes_the_operator(self):
        operator = ReturnOperator()
        assert 'return' in operator.description.lower()


@pytest.mark.small
class DescribeReturnOperatorCanMutate:
    """Test the can_mutate method."""

    def it_returns_true_for_return_with_value(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        assert operator.can_mutate(return_node) is True

    def it_returns_true_for_return_with_expression(self):
        operator = ReturnOperator()
        source = """
def foo():
    return x + y
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        assert operator.can_mutate(return_node) is True

    def it_returns_false_for_bare_return(self):
        operator = ReturnOperator()
        source = """
def foo():
    return
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        assert operator.can_mutate(return_node) is False

    def it_returns_false_for_return_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return None
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        assert operator.can_mutate(return_node) is False

    def it_returns_false_for_non_return_node(self):
        operator = ReturnOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False


@pytest.mark.small
class DescribeReturnOperatorMutate:
    """Test the mutate method."""

    def it_return_expression_mutates_only_to_none(self):
        """For return x + y, mutate() returns exactly 1 mutation (return None), not a boolean flip."""
        operator = ReturnOperator()
        source = """
def foo():
    return x + y
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Return)
        assert mutations[0].value is None

    def it_mutates_return_value_to_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Return)
        assert mutations[0].value is None

    def it_mutates_return_true_to_false(self):
        operator = ReturnOperator()
        source = """
def foo():
    return True
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert len(mutations) == 2
        assert all(isinstance(m, ast.Return) for m in mutations)
        mutation_values = {m.value.value if isinstance(m.value, ast.Constant) else None for m in mutations}
        assert None in mutation_values
        assert False in mutation_values

    def it_mutates_return_false_to_true(self):
        operator = ReturnOperator()
        source = """
def foo():
    return False
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert all(isinstance(m, ast.Return) for m in mutations)
        mutation_values = {m.value.value if isinstance(m.value, ast.Constant) else None for m in mutations}
        assert None in mutation_values
        assert True in mutation_values

    def it_does_not_modify_the_original_node(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]
        assert isinstance(return_node, ast.Return)
        assert isinstance(return_node.value, ast.Constant)
        original_value = return_node.value.value

        operator.mutate(return_node)

        assert isinstance(return_node.value, ast.Constant)
        assert return_node.value.value == original_value

    def it_returns_empty_list_for_unsupported_node(self):
        operator = ReturnOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def it_returns_empty_list_for_bare_return(self):
        operator = ReturnOperator()
        source = """
def foo():
    return
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert mutations == []

    def it_returns_empty_list_for_return_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return None
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        assert mutations == []

    def it_mutates_return_empty_list_to_list_with_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return []
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return_node = func_def.body[0]

        mutations = operator.mutate(return_node)

        none_mutations = [m for m in mutations if isinstance(m, ast.Return) and m.value is None]
        assert len(none_mutations) == 1
