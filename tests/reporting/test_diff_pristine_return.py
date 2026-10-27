"""The HTML diff of a return gremlin shows the user's statement, not switch code."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.reporting.html import HtmlReporter


@pytest.mark.small
class DescribeReturnGremlinDiff:
    def it_renders_a_diff_without_switch_code(self):
        gremlins, _ = transform_source('def target(age):\n    return age >= 18\n', 'm.py')
        gremlin = next(g for g in gremlins if isinstance(g.original_node, ast.Return))

        html = HtmlReporter()._render_diff_panel(gremlin)

        assert 'return age &gt;= 18' in html
        assert '__gremlin_active__' not in html
