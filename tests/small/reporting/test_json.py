"""Tests for the JSON reporter."""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.json_reporter import JsonReporter
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
        killing_test: str | None = None,
    ) -> GremlinResult:
        gremlin = make_gremlin(
            file_path=file_path,
            line_number=line_number,
            operator_name=operator_name,
            description=description,
        )
        return GremlinResult(gremlin=gremlin, status=status, killing_test=killing_test)

    return _make_result


class TestJsonReporterOutput:
    """Tests for JSON reporter structure."""

    def test_produces_valid_json(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        json_str = reporter.to_json(score)

        # Should not raise
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_includes_summary_section(self, make_result):
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

    def test_includes_percentage_in_summary(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'percentage' in data['summary']
        assert data['summary']['percentage'] == 50.0

    def test_includes_results_array(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert 'results' in data
        assert len(data['results']) == 2


class TestJsonReporterResultFormat:
    """Tests for individual result format in JSON."""

    def test_result_includes_gremlin_id(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['gremlin_id'] == 'g001'

    def test_result_includes_file_and_line(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py', line_number=42)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['file_path'] == 'src/auth.py'
        assert data['results'][0]['line_number'] == 42

    def test_result_includes_status(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['status'] == 'survived'

    def test_result_includes_operator_and_description(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                operator_name='boundary',
                description='>= 18 to >= 19',
            )
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['operator'] == 'boundary'
        assert data['results'][0]['description'] == '>= 18 to >= 19'

    def test_result_includes_killing_test_when_present(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                killing_test='test_age_validation',
            )
        ]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()

        data = json.loads(reporter.to_json(score))

        assert data['results'][0]['killing_test'] == 'test_age_validation'


class TestJsonReporterFileOutput:
    """Tests for writing JSON to file."""

    def test_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()
        output_file = tmp_path / 'report.json'

        reporter.write_report(score, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert 'summary' in data

    def test_writes_formatted_json(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = JsonReporter()
        output_file = tmp_path / 'report.json'

        reporter.write_report(score, output_file)

        content = output_file.read_text()
        # Pretty-printed JSON has newlines
        assert '\n' in content


class TestJsonReporterFileBreakdown:
    """Tests for per-file breakdown in JSON."""

    def test_includes_files_section(self, make_result):
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

    def test_file_breakdown_includes_per_file_stats(self, make_result):
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
