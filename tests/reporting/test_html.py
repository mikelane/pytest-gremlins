"""Tests for the HTML reporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.reporting.html import HtmlReporter, resolve_html_output_path
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


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


@pytest.mark.small
class DescribeHtmlReporterOutputLocation:
    """Tests for Epic A: write_report creates parent directories automatically.

    References: #155, #157
    """

    def it_creates_nested_parent_directories_before_writing(self, make_result, tmp_path: Path):
        # write_text without mkdir raises FileNotFoundError for missing parents.
        # This test fails if mkdir(parents=True) is absent from write_report.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        nested = tmp_path / 'coverage' / 'gremlins' / 'index.html'

        reporter.write_report(score, nested)

        assert nested.exists()
        assert '<!DOCTYPE html>' in nested.read_text()

    def it_writes_to_the_exact_nested_path_not_a_sibling(self, make_result, tmp_path: Path):
        # Hardcoding 'gremlin-report.html' next to rootdir would fail this assertion.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        exact = tmp_path / 'deep' / 'nested' / 'index.html'

        reporter.write_report(score, exact)

        assert exact.exists()
        assert not (tmp_path / 'deep' / 'nested.html').exists()
        assert not (tmp_path / 'index.html').exists()

    def it_succeeds_when_parent_directory_already_exists(self, make_result, tmp_path: Path):
        # exist_ok=True must be set; without it a second mkdir raises FileExistsError.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        output = tmp_path / 'coverage' / 'gremlins' / 'index.html'
        output.parent.mkdir(parents=True, exist_ok=True)

        reporter.write_report(score, output)  # must not raise

        assert output.exists()


@pytest.mark.small
class DescribeResolveHtmlOutputPath:
    """Tests for Epic A: resolve_html_output_path pure function.

    References: #155, #156
    """

    def it_returns_coverage_gremlins_index_when_no_custom_dir(self, tmp_path: Path):
        result = resolve_html_output_path(rootdir=tmp_path, html_dir=None)

        # Must be exactly <rootdir>/coverage/gremlins/index.html, not rootdir/gremlin-report.html.
        assert result == tmp_path / 'coverage' / 'gremlins' / 'index.html'

    def it_returns_custom_dir_slash_index_when_html_dir_provided(self, tmp_path: Path):
        custom = tmp_path / 'my-reports'
        result = resolve_html_output_path(rootdir=tmp_path, html_dir=custom)

        # Must append index.html to the custom dir, not the default subpath.
        assert result == custom / 'index.html'

    def it_does_not_embed_coverage_gremlins_when_custom_dir_given(self, tmp_path: Path):
        custom = tmp_path / 'out'
        result = resolve_html_output_path(rootdir=tmp_path, html_dir=custom)

        # A naïve impl that always appends coverage/gremlins would fail here.
        assert 'coverage' not in result.parts
        assert 'gremlins' not in result.parts

    def it_uses_rootdir_not_cwd_for_default_path(self, tmp_path: Path):
        different_rootdir = tmp_path / 'project-root'
        result = resolve_html_output_path(rootdir=different_rootdir, html_dir=None)

        # The default path must be anchored at rootdir, not at tmp_path or cwd.
        assert result == different_rootdir / 'coverage' / 'gremlins' / 'index.html'
        assert tmp_path not in result.parents or result.is_relative_to(different_rootdir)

    def it_resolves_relative_html_dir_against_rootdir(self, tmp_path: Path):
        # When --gremlins-html-dir is passed as a relative string (e.g. "reports"),
        # resolve_html_output_path must anchor it to rootdir, not to cwd.
        # A naïve impl that uses html_dir as-is returns a relative path like
        # 'reports/index.html' instead of '<rootdir>/reports/index.html'.
        relative_html_dir = Path('reports')

        result = resolve_html_output_path(rootdir=tmp_path, html_dir=relative_html_dir)

        assert result.is_absolute()
        assert result == tmp_path / 'reports' / 'index.html'
