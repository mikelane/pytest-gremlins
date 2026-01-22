"""Tests for the HTML reporter."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def make_gremlin():
    """Factory fixture for creating test gremlins."""
    counter = 0

    def _make_gremlin(
        file_path: str = 'test.py',
        line_number: int = 1,
        operator_name: str = 'comparison',
        description: str = '>= to >',
    ) -> Gremlin:
        nonlocal counter
        counter += 1
        return Gremlin(
            gremlin_id=f'g{counter:03d}',
            file_path=file_path,
            line_number=line_number,
            original_node=ast.parse('x >= 0', mode='eval').body,
            mutated_node=ast.parse('x > 0', mode='eval').body,
            operator_name=operator_name,
            description=description,
        )

    return _make_gremlin


@pytest.fixture
def make_result(make_gremlin):
    """Factory fixture for creating test results."""

    def _make_result(
        status: GremlinResultStatus = GremlinResultStatus.ZAPPED,
        file_path: str = 'test.py',
        line_number: int = 1,
        operator_name: str = 'comparison',
        description: str = '>= to >',
    ) -> GremlinResult:
        gremlin = make_gremlin(
            file_path=file_path,
            line_number=line_number,
            operator_name=operator_name,
            description=description,
        )
        return GremlinResult(gremlin=gremlin, status=status)

    return _make_result


class TestHtmlReporterBasicStructure:
    """Tests for basic HTML structure."""

    def test_produces_valid_html(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        assert '<html' in html
        assert '</html>' in html

    def test_includes_head_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<head>' in html
        assert '</head>' in html
        assert '<title>' in html

    def test_includes_body_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<body>' in html
        assert '</body>' in html


class TestHtmlReporterContent:
    """Tests for HTML content."""

    def test_includes_title(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'pytest-gremlins' in html.lower() or 'mutation' in html.lower()

    def test_includes_summary_stats(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '50' in html  # 50% score
        assert 'zapped' in html.lower() or '1' in html

    def test_includes_results_table(self, make_result):
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

    def test_highlights_survived_gremlins(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have some visual distinction for survived
        assert 'survived' in html.lower()


class TestHtmlReporterFileOutput:
    """Tests for writing HTML to file."""

    def test_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        output_file = tmp_path / 'report.html'

        reporter.write_report(score, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert '<!DOCTYPE html>' in content

    def test_includes_styles(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have embedded CSS for standalone report
        assert '<style>' in html or 'style=' in html


class TestHtmlReporterEmpty:
    """Tests for handling empty results."""

    def test_handles_empty_results(self):
        score = MutationScore.from_results([])
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        # Should indicate no results rather than crash
        assert 'no' in html.lower() or '0' in html
