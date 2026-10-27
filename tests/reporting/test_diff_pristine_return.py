"""The HTML diff of a return gremlin shows the user's statement, not switch code."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeReturnGremlinDiff:
    def it_renders_a_diff_without_switch_code(self):
        gremlins, _ = transform_source('def target(age):\n    return age >= 18\n', 'm.py')
        gremlin = next(g for g in gremlins if isinstance(g.original_node, ast.Return))

        score = MutationScore.from_results([GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)])

        html = HtmlReporter().to_html(score)

        assert 'return age &gt;= 18' in html
        assert '__gremlin_active__' not in html
