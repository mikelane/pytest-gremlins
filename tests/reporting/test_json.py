"""Tests for the JSON reporter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class DescribeJsonReporterOutput:
    """Tests for JSON reporter structure."""

    def it_produces_valid_json(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        json_str = reporter.to_json(score)

        # Should not raise
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def it_includes_summary_section(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'summary' in data
        assert data['summary']['total'] == 2
        assert data['summary']['zapped'] == 1
        assert data['summary']['survived'] == 1

    def it_includes_percentage_in_summary(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'percentage' in data['summary']
        assert data['summary']['percentage'] == 50.0

    def it_includes_results_array(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'results' in data
        assert len(data['results']) == 2


@pytest.mark.small
class DescribeJsonReporterResultFormat:
    """Tests for individual result format in JSON."""

    def it_includes_gremlin_id(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['gremlin_id'] == 'g001'

    def it_includes_file_and_line(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py', line_number=42)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['file_path'] == 'src/auth.py'
        assert data['results'][0]['line_number'] == 42

    def it_includes_status(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['status'] == 'survived'

    def it_includes_operator_and_description(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                operator_name='boundary',
                description='>= 18 to >= 19',
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['operator'] == 'boundary'
        assert data['results'][0]['description'] == '>= 18 to >= 19'

    def it_includes_killing_test_when_present(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                killing_test='test_age_validation',
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['killing_test'] == 'test_age_validation'


@pytest.mark.medium
class DescribeJsonReporterFileOutput:
    """Tests for writing JSON to file."""

    def it_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()
        output_file = tmp_path / 'report.json'

        reporter.write_report(score, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert 'summary' in data

    def it_writes_formatted_json(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()
        output_file = tmp_path / 'report.json'

        reporter.write_report(score, output_file)

        content = output_file.read_text()
        # Pretty-printed JSON has newlines
        assert '\n' in content


@pytest.mark.small
class DescribeJsonReporterFileBreakdown:
    """Tests for per-file breakdown in JSON."""

    def it_includes_files_section(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='utils.py'),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'files' in data
        assert 'auth.py' in data['files']
        assert 'utils.py' in data['files']

    def it_includes_per_file_stats_in_file_breakdown(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='auth.py'),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        auth_stats = data['files']['auth.py']
        assert auth_stats['total'] == 3
        assert auth_stats['zapped'] == 2
        assert auth_stats['survived'] == 1
        assert auth_stats['percentage'] == pytest.approx(66.67, rel=0.01)


@pytest.mark.small
class DescribeJsonReporterSelectedTests:
    """Tests for selected_tests and execution_time_ms in JSON results."""

    def it_includes_selected_tests_when_present(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.SURVIVED,
                selected_tests=['tests/test_a.py::test_foo', 'tests/test_b.py::test_bar'],
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['selected_tests'] == ['tests/test_a.py::test_foo', 'tests/test_b.py::test_bar']

    def it_includes_execution_time_ms_when_present(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                execution_time_ms=123.45,
            ),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['execution_time_ms'] == 123.45

    def it_omits_selected_tests_when_empty(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'selected_tests' not in data['results'][0]

    def it_omits_execution_time_ms_when_none(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'execution_time_ms' not in data['results'][0]
