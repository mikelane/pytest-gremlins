"""Tests for the console reporter."""

from __future__ import annotations

import ast
from io import StringIO

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.console import ConsoleReporter
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


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


class TestConsoleReporter:
    """Tests for console reporter output."""

    def test_reporter_writes_header(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'pytest-gremlins mutation report' in output_text

    def test_reporter_writes_summary_line(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Zapped: 2 gremlins' in output_text
        # 66.67% rounds to 67%
        assert '67%' in output_text or '66%' in output_text

    def test_reporter_writes_survived_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Survived: 2 gremlins' in output_text

    def test_reporter_writes_top_survivors(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.SURVIVED,
                file_path='src/auth.py',
                line_number=42,
                description='>= to >',
            ),
            make_result(
                GremlinResultStatus.SURVIVED,
                file_path='src/utils.py',
                line_number=17,
                description='+ to -',
            ),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Top surviving gremlins:' in output_text
        assert 'src/auth.py:42' in output_text
        assert 'src/utils.py:17' in output_text

    def test_reporter_omits_survivors_section_when_none(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED) for _ in range(5)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Top surviving gremlins:' not in output_text

    def test_reporter_writes_footer(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        # Should have border at top and bottom
        assert output_text.count('=') >= 40  # Multiple = signs for borders


class TestConsoleReporterFormatting:
    """Tests for console reporter formatting details."""

    def test_formats_percentage_with_rounding(self, make_result):
        # Create 3 results: 2 zapped, 1 survived = 66.67%
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        # Should round to whole number or one decimal
        assert '67%' in output_text or '66.7%' in output_text or '66%' in output_text

    def test_handles_zero_results_gracefully(self):
        score = MutationScore.from_results([])
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'No gremlins tested' in output_text or '0 gremlins' in output_text

    def test_includes_hint_for_detailed_report(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert '--gremlin-report=html' in output_text or 'html' in output_text.lower()
