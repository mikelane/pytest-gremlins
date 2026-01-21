"""Tests for the ReturnOperator."""

from __future__ import annotations

import ast

from pytest_gremlins.operators.protocol import GremlinOperator
from pytest_gremlins.operators.return_value import ReturnOperator


class TestReturnOperatorProtocol:
    """Test that ReturnOperator implements the GremlinOperator protocol."""

    def test_implements_gremlin_operator_protocol(self):
        operator = ReturnOperator()
        assert isinstance(operator, GremlinOperator)

    def test_name_is_return(self):
        operator = ReturnOperator()
        assert operator.name == 'return'

    def test_description_describes_the_operator(self):
        operator = ReturnOperator()
        assert 'return' in operator.description.lower()


class TestReturnOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_return_with_value(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        assert operator.can_mutate(return_node) is True

    def test_returns_true_for_return_with_expression(self):
        operator = ReturnOperator()
        source = """
def foo():
    return x + y
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        assert operator.can_mutate(return_node) is True

    def test_returns_false_for_bare_return(self):
        operator = ReturnOperator()
        source = """
def foo():
    return
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        assert operator.can_mutate(return_node) is False

    def test_returns_false_for_return_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return None
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        assert operator.can_mutate(return_node) is False

    def test_returns_false_for_non_return_node(self):
        operator = ReturnOperator()
        node = ast.parse('x + 10', mode='eval').body

        assert operator.can_mutate(node) is False


class TestReturnOperatorMutate:
    """Test the mutate method."""

    def test_return_value_mutates_to_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        mutations = operator.mutate(return_node)

        assert len(mutations) == 1
        assert isinstance(mutations[0], ast.Return)
        assert mutations[0].value is None

    def test_return_true_mutates_to_false(self):
        operator = ReturnOperator()
        source = """
def foo():
    return True
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        mutations = operator.mutate(return_node)

        assert len(mutations) == 2
        mutation_values = []
        for m in mutations:
            if m.value is None:
                mutation_values.append(None)
            elif isinstance(m.value, ast.Constant):
                mutation_values.append(m.value.value)

        assert None in mutation_values
        assert False in mutation_values

    def test_return_false_mutates_to_true(self):
        operator = ReturnOperator()
        source = """
def foo():
    return False
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        mutations = operator.mutate(return_node)

        mutation_values = []
        for m in mutations:
            if m.value is None:
                mutation_values.append(None)
            elif isinstance(m.value, ast.Constant):
                mutation_values.append(m.value.value)

        assert None in mutation_values
        assert True in mutation_values

    def test_original_node_is_not_modified(self):
        operator = ReturnOperator()
        source = """
def foo():
    return 42
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]
        original_value = return_node.value.value

        operator.mutate(return_node)

        assert return_node.value.value == original_value

    def test_returns_empty_list_for_unsupported_node(self):
        operator = ReturnOperator()
        node = ast.parse('x + 10', mode='eval').body

        mutations = operator.mutate(node)

        assert mutations == []

    def test_return_empty_list_mutates_to_list_with_none(self):
        operator = ReturnOperator()
        source = """
def foo():
    return []
"""
        tree = ast.parse(source)
        return_node = tree.body[0].body[0]

        mutations = operator.mutate(return_node)

        has_none_mutation = any(m.value is None for m in mutations)
        assert has_none_mutation
