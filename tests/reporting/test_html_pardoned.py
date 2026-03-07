"""Tests for pardoned gremlin rendering in the HTML reporter."""

from __future__ import annotations

import pytest

from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeHtmlSummaryPardonedCard:
    """Tests that the summary section shows a pardoned stat card."""

    def it_includes_pardoned_card_when_pardoned_exist(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        html = HtmlReporter().to_html(score)
        assert 'Pardoned' in html

    def it_excludes_pardoned_card_when_none_exist(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        html = HtmlReporter().to_html(score)
        assert 'Pardoned' not in html


@pytest.mark.small
class DescribeHtmlScoreLineWithPardoned:
    """Tests that the score line includes pardoned count."""

    def it_score_line_includes_pardoned_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        html = HtmlReporter().to_html(score)
        # Pardoned stat card renders the count value and label
        assert '>1<' in html
        assert 'Pardoned' in html


@pytest.mark.small
class DescribeHtmlPardonedSection:
    """Tests for the pardoned gremlins section in the HTML report."""

    def it_renders_pardoned_section_when_pardoned_results_exist(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(
                GremlinResultStatus.PARDONED,
                file_path='auth.py',
                line_number=42,
                description='// to /',
                pardon_reason='equivalent: floor division is integer arithmetic',
            ),
        ]
        score = MutationScore.from_results(results)
        html = HtmlReporter().to_html(score)
        assert 'Pardoned Gremlins' in html
        assert 'auth.py' in html
        assert '42' in html
        assert 'equivalent: floor division is integer arithmetic' in html

    def it_omits_pardoned_section_when_no_pardoned_results(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        html = HtmlReporter().to_html(score)
        assert 'Pardoned Gremlins' not in html
