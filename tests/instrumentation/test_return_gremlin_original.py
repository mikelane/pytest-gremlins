"""Return gremlins keep the user's source as their original, not the instrumented switch."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.reporting.html import HtmlReporter


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

    def it_renders_a_diff_without_switch_code(self):
        gremlin = _return_gremlins('return age >= 18')[0]

        html = HtmlReporter()._render_diff_panel(gremlin)

        assert 'return age &gt;= 18' in html or 'return age >= 18' in html
        assert '__gremlin_active__' not in html
