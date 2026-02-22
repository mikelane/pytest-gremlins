"""Tests for the HTML reporter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class DescribeHtmlReporterBasicStructure:
    """Tests for basic HTML structure."""

    def it_produces_valid_html(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        assert '<html' in html
        assert '</html>' in html

    def it_includes_head_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<head>' in html
        assert '</head>' in html
        assert '<title>' in html

    def it_includes_body_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<body>' in html
        assert '</body>' in html


@pytest.mark.small
class DescribeHtmlReporterContent:
    """Tests for HTML content."""

    def it_includes_title(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'pytest-gremlins' in html.lower() or 'mutation' in html.lower()

    def it_includes_summary_stats(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '50' in html  # 50% score
        assert 'zapped' in html.lower() or '1' in html

    def it_includes_results_table(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py', line_number=42),
            make_result(GremlinResultStatus.SURVIVED, file_path='utils.py', line_number=17),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'auth.py' in html
        assert 'utils.py' in html
        assert '42' in html
        assert '17' in html

    def it_highlights_survived_gremlins(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have some visual distinction for survived
        assert 'survived' in html.lower()


@pytest.mark.small
class DescribeHtmlReporterFileOutput:
    """Tests for writing HTML to file."""

    def it_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        output_file = tmp_path / 'report.html'

        reporter.write_report(score, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert '<!DOCTYPE html>' in content

    def it_includes_styles(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have embedded CSS for standalone report
        assert '<style>' in html or 'style=' in html


@pytest.mark.small
class DescribeHtmlReporterEmpty:
    """Tests for handling empty results."""

    def it_produces_valid_html_with_zero_indicator_for_empty_results(self):
        score = MutationScore.from_results([])
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        # Must indicate no results rather than crash
        assert 'no' in html.lower() or '0' in html


@pytest.mark.small
class DescribeHtmlReporterAllOutcomeCategories:
    """Tests for displaying all mutation outcome categories in HTML."""

    def it_displays_timeout_card_when_timeouts_present(self, make_result):
        """It displays a timeout stat card when there are timeout results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have timeout card with count
        assert 'stat-timeout' in html
        assert 'Timeout' in html
        assert '>2<' in html  # 2 timeouts

    def it_displays_error_card_when_errors_present(self, make_result):
        """It displays an error stat card when there are error results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have error card with count
        assert 'stat-error' in html
        assert 'Error' in html
        assert '>1<' in html  # 1 error

    def it_omits_timeout_card_when_no_timeouts(self, make_result):
        """It omits the timeout card when there are no timeout results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should not have timeout card
        assert 'stat-timeout' not in html
        # But should have zapped, survived, and error
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-error' in html

    def it_omits_error_card_when_no_errors(self, make_result):
        """It omits the error card when there are no error results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should not have error card
        assert 'stat-error' not in html
        # But should have zapped, survived, and timeout
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-timeout' in html

    def it_displays_all_four_outcome_cards_when_mixed_results(self, make_result):
        """It displays all four stat cards (zapped, survived, timeout, error) when all outcomes present."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have all four stat cards
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-timeout' in html
        assert 'stat-error' in html
        # Verify counts
        assert '>2<' in html  # 2 zapped
        assert '>1<' in html  # 1 survived, 1 timeout, 1 error
