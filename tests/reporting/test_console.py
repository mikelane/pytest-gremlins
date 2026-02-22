"""Tests for the console reporter."""

from __future__ import annotations

from io import StringIO

import pytest

from pytest_gremlins.reporting.console import ConsoleReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeConsoleReporter:
    """Tests for console reporter output."""

    def it_reporter_writes_header(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'pytest-gremlins mutation report' in output_text

    def it_reporter_writes_summary_line(self, make_result):
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

    def it_reporter_writes_survived_count(self, make_result):
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

    def it_write_summary_returns_early_when_total_is_zero(self) -> None:
        """_write_summary with total=0 writes nothing (defensive guard)."""
        score = MutationScore.from_results([])
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter._write_summary(score)

        assert output.getvalue() == ''

    def it_reporter_writes_top_survivors(self, make_result):
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

    def it_reporter_omits_survivors_section_when_none(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED) for _ in range(5)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Top surviving gremlins:' not in output_text

    def it_reporter_writes_footer(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        # Should have border at top and bottom
        assert output_text.count('=') >= 40  # Multiple = signs for borders


@pytest.mark.small
class DescribeConsoleReporterFormatting:
    """Tests for console reporter formatting details."""

    def it_formats_percentage_with_rounding(self, make_result):
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

    def it_outputs_no_gremlins_message_for_empty_results(self):
        score = MutationScore.from_results([])
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'No gremlins tested' in output_text or '0 gremlins' in output_text

    def it_includes_hint_for_detailed_report(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert '--gremlin-report=html' in output_text or 'html' in output_text.lower()


@pytest.mark.small
class DescribeConsoleReporterAllOutcomeCategories:
    """Tests for all mutation outcome categories (zapped, survived, timeout, error)."""

    def it_displays_all_four_categories_with_mixed_results(self, make_result):
        """It displays zapped, survived, timeout, and error with correct counts and percentages."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),  # 4 zapped = 40%
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.SURVIVED),  # 2 survived = 20%
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),  # 3 timeout = 30%
            make_result(GremlinResultStatus.ERROR),  # 1 error = 10%
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Zapped: 4 gremlins (40%)' in output_text
        assert 'Survived: 2 gremlins (20%)' in output_text
        assert 'Timeout: 3 gremlins (30%)' in output_text
        assert 'Error: 1 gremlins (10%)' in output_text

    def it_omits_timeout_line_when_zero_timeouts(self, make_result):
        """It omits the timeout line when there are no timeouts."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Zapped:' in output_text
        assert 'Survived:' in output_text
        assert 'Error:' in output_text
        assert 'Timeout:' not in output_text

    def it_omits_error_line_when_zero_errors(self, make_result):
        """It omits the error line when there are no errors."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Zapped:' in output_text
        assert 'Survived:' in output_text
        assert 'Timeout:' in output_text
        assert 'Error:' not in output_text

    def it_percentages_computed_from_own_counts_not_complement(self, make_result):
        """It computes each percentage from its own count, not as 100 - other_percent."""
        # 5 zapped (50%), 1 survived (10%), 2 timeout (20%), 2 error (20%) = 10 total
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),  # 5 = 50%
            make_result(GremlinResultStatus.SURVIVED),  # 1 = 10%
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),  # 2 = 20%
            make_result(GremlinResultStatus.ERROR),
            make_result(GremlinResultStatus.ERROR),  # 2 = 20%
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        # Verify survived is 10%, not 100 - 50 = 50%
        assert 'Survived: 1 gremlins (10%)' in output_text
        assert 'Timeout: 2 gremlins (20%)' in output_text
        assert 'Error: 2 gremlins (20%)' in output_text
