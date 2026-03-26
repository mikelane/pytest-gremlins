"""Tests for error_output field propagation through the reporting pipeline.

Verifies that error_output is captured, stored, and rendered correctly
across all data models, reporters, and export formats.
"""

from __future__ import annotations

from io import StringIO
import json

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.types import CachedGremlinResult
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.console import ConsoleReporter
from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import StrykerExporter


@pytest.mark.small
class DescribeGremlinResultErrorOutput:
    """Tests for error_output field on GremlinResult."""

    def it_stores_error_output(self, make_result) -> None:
        result = make_result(
            GremlinResultStatus.ERROR,
            error_output='ImportError: No module named foo',
        )
        assert result.error_output == 'ImportError: No module named foo'

    def it_defaults_error_output_to_empty_string(self, make_result) -> None:
        result = make_result(GremlinResultStatus.ERROR)
        assert result.error_output == ''


@pytest.mark.small
class DescribeWorkerResultErrorOutput:
    """Tests for error_output field on WorkerResult."""

    def it_stores_error_output(self) -> None:
        result = WorkerResult(
            gremlin_id='g001',
            status=GremlinResultStatus.ERROR,
            error_output='subprocess crashed',
        )
        assert result.error_output == 'subprocess crashed'

    def it_defaults_error_output_to_empty_string(self) -> None:
        result = WorkerResult(
            gremlin_id='g001',
            status=GremlinResultStatus.ERROR,
        )
        assert result.error_output == ''


@pytest.mark.small
class DescribeMutationScoreTopErrors:
    """Tests for MutationScore.top_errors() method."""

    def it_returns_only_error_results_with_nonempty_error_output(self, make_result) -> None:
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ERROR, error_output='crash 1'),
            make_result(GremlinResultStatus.ERROR),  # empty error_output
            make_result(GremlinResultStatus.ERROR, error_output='crash 2'),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)

        errors = score.top_errors()
        assert len(errors) == 2
        assert all(r.status == GremlinResultStatus.ERROR for r in errors)
        assert all(r.error_output for r in errors)

    def it_respects_limit_parameter(self, make_result) -> None:
        results = [make_result(GremlinResultStatus.ERROR, error_output=f'crash {i}') for i in range(10)]
        score = MutationScore.from_results(results)

        errors = score.top_errors(limit=3)
        assert len(errors) == 3


@pytest.mark.small
class DescribeConsoleReporterErrorOutput:
    """Tests for error details in console output."""

    def it_prints_error_details_when_errors_exist(self, make_result) -> None:
        results = [
            make_result(
                GremlinResultStatus.ERROR,
                file_path='src/auth.py',
                line_number=42,
                error_output='ImportError: No module named foo',
            ),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Top errored gremlins:' in output_text
        assert 'src/auth.py:42' in output_text
        assert 'ImportError: No module named foo' in output_text

    def it_prints_nothing_extra_when_no_errors(self, make_result) -> None:
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        output = StringIO()
        reporter = ConsoleReporter(output=output)

        reporter.write_report(score)

        output_text = output.getvalue()
        assert 'Top errored gremlins:' not in output_text


@pytest.mark.small
class DescribeHtmlReporterErrorOutput:
    """Tests for error details in HTML output."""

    def it_renders_errors_section_with_collapsible_stderr(self, make_result) -> None:
        results = [
            make_result(
                GremlinResultStatus.ERROR,
                file_path='src/auth.py',
                line_number=42,
                operator_name='comparison',
                error_output='Traceback:\n  File "test.py"\nImportError: boom',
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'Errored Gremlins' in html
        assert '<details>' in html
        assert 'ImportError: boom' in html
        assert 'src/auth.py' in html

    def it_omits_errors_section_when_no_errors_have_error_output(self, make_result) -> None:
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'Errored Gremlins' not in html


@pytest.mark.small
class DescribeJsonReporterErrorOutput:
    """Tests for error_output in JSON report."""

    def it_includes_error_output_for_errored_gremlins(self, make_result) -> None:
        results = [
            make_result(
                GremlinResultStatus.ERROR,
                error_output='ImportError: No module named foo',
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['error_output'] == 'ImportError: No module named foo'

    def it_omits_error_output_key_for_non_errored_gremlins(self, make_result) -> None:
        results = [
            make_result(GremlinResultStatus.ZAPPED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'error_output' not in data['results'][0]


@pytest.mark.small
class DescribeStrykerExporterErrorOutput:
    """Tests for statusReason in Stryker export."""

    def it_includes_status_reason_for_errored_gremlins(self, make_result) -> None:
        results = [
            make_result(
                GremlinResultStatus.ERROR,
                error_output='ImportError: No module named foo',
            ),
        ]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert mutant['statusReason'] == 'ImportError: No module named foo'

    def it_omits_status_reason_for_non_errored_gremlins(self, make_result) -> None:
        results = [
            make_result(GremlinResultStatus.ZAPPED),
        ]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'statusReason' not in mutant


@pytest.mark.medium
class DescribeCachedGremlinResultErrorOutput:
    """Tests for error_output in cache round-trip."""

    def it_round_trips_error_output_through_cache(self, tmp_path) -> None:
        cache = IncrementalCache(tmp_path / '.gremlins_cache')
        cached_result = CachedGremlinResult(
            status='error',
            killing_test=None,
            execution_time_ms=42.0,
            error_output='ImportError: No module named foo',
        )
        cache.cache_result(
            gremlin_id='g001',
            source_hash='abc123',
            test_hashes={'test_foo': 'def456'},
            result=cached_result,
        )

        retrieved = cache.get_cached_result(
            gremlin_id='g001',
            source_hash='abc123',
            test_hashes={'test_foo': 'def456'},
        )

        assert retrieved is not None
        assert retrieved['error_output'] == 'ImportError: No module named foo'
        cache.close()

    def it_deserializes_old_cache_entries_without_error_output(self, tmp_path) -> None:
        cache = IncrementalCache(tmp_path / '.gremlins_cache')
        # Simulate an old-format entry by casting a dict without error_output
        old_result: CachedGremlinResult = {  # type: ignore[typeddict-item]
            'status': 'zapped',
            'killing_test': 'test_foo',
            'execution_time_ms': 10.0,
        }
        cache.cache_result(
            gremlin_id='g002',
            source_hash='abc123',
            test_hashes={'test_foo': 'def456'},
            result=old_result,
        )

        retrieved = cache.get_cached_result(
            gremlin_id='g002',
            source_hash='abc123',
            test_hashes={'test_foo': 'def456'},
        )

        assert retrieved is not None
        # Old entries lack the key — caller uses .get('error_output', '')
        assert retrieved.get('error_output', '') == ''
        cache.close()


@pytest.mark.small
class DescribeAggregatorAddErrorOutput:
    """Tests for error_output in aggregator.add_error()."""

    def it_captures_exception_message_in_error_output(self) -> None:
        aggregator = ResultAggregator(total_gremlins=1)
        aggregator.add_error('g001', Exception('Worker crashed hard'))

        results = aggregator.get_results()
        assert len(results) == 1
        assert results[0].error_output == 'Worker crashed hard'
