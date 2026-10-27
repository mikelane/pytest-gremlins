"""Return gremlins keep the user's source as their original, not the instrumented switch."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source


def _return_gremlins(statement: str):
    gremlins, _ = transform_source(f'def target(a, b, age):\n    {statement}\n', 'm.py')
    return [g for g in gremlins if isinstance(g.original_node, ast.Return)]


@pytest.mark.small
class DescribeReturnGremlinOriginal:
    @pytest.mark.parametrize(
        'statement',
        ['return age >= 18', 'return True', 'return a + b', 'return a and not b'],
    )
    def it_keeps_the_statement_as_written(self, statement):
        gremlins = _return_gremlins(statement)

        assert gremlins
        assert {ast.unparse(g.original_node) for g in gremlins} == {ast.unparse(ast.parse(statement))}


MAIN_RETURN_TRUE = [
    ('m_f6f7_g001', 'boolean', 'True to False', 2),
    ('m_f6f7_g002', 'return', 'return value to None', 2),
]

MAIN_RETURN_FALSE_THEN_COMPARE = [
    ('m_f6f7_g001', 'boolean', 'False to True', 2),
    ('m_f6f7_g002', 'return', 'return value to None', 2),
    ('m_f6f7_g003', 'comparison', '>= to >', 5),
    ('m_f6f7_g004', 'comparison', '>= to <', 5),
    ('m_f6f7_g005', 'boundary', 'boundary shift +/-1', 5),
    ('m_f6f7_g006', 'boundary', 'boundary shift +/-1', 5),
    ('m_f6f7_g007', 'return', 'return value to None', 5),
]


def _inventory(source: str):
    gremlins, _ = transform_source(source, 'm.py')
    return [(g.gremlin_id, g.operator_name, g.description, g.line_number) for g in gremlins]


@pytest.mark.small
class DescribeReturnGremlinIdentityMatchesMain:
    def it_creates_the_same_gremlins_as_main_for_return_true(self):
        assert _inventory('def f():\n    return True\n') == MAIN_RETURN_TRUE

    def it_keeps_later_gremlin_ids_stable_after_return_false(self):
        source = 'def g():\n    return False\n\ndef h(age):\n    return age >= 18\n'

        assert _inventory(source) == MAIN_RETURN_FALSE_THEN_COMPARE

    def it_keeps_the_return_node_position(self):
        gremlins = _return_gremlins('return age >= 18')

        assert {
            (g.original_node.lineno, g.original_node.col_offset, g.original_node.end_col_offset) for g in gremlins
        } == {(2, 4, 20)}
