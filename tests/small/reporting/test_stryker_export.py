"""Tests for the Stryker Dashboard JSON exporter.

The Stryker Dashboard uses a standardized mutation-testing-report-schema.
This exporter converts pytest-gremlins results into that format for
compatibility with the Stryker Dashboard and other tools that use
the schema.

See: https://github.com/stryker-mutator/mutation-testing-elements
"""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import StrykerExporter


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def make_gremlin():
    """Factory fixture for creating test gremlins."""
    counter = 0

    def _make_gremlin(
        file_path: str = 'test.py',
        line_number: int = 1,
        column_offset: int = 0,
        end_line_number: int | None = None,
        end_column_offset: int | None = None,
        operator_name: str = 'comparison',
        description: str = '>= to >',
    ) -> Gremlin:
        nonlocal counter
        counter += 1
        node = ast.parse('x >= 0', mode='eval').body
        node.lineno = line_number
        node.col_offset = column_offset
        node.end_lineno = end_line_number or line_number
        node.end_col_offset = end_column_offset or (column_offset + 6)
        return Gremlin(
            gremlin_id=f'g{counter:03d}',
            file_path=file_path,
            line_number=line_number,
            original_node=node,
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
        execution_time_ms: float | None = None,
    ) -> GremlinResult:
        gremlin = make_gremlin(
            file_path=file_path,
            line_number=line_number,
            operator_name=operator_name,
            description=description,
        )
        return GremlinResult(
            gremlin=gremlin,
            status=status,
            killing_test=killing_test,
            execution_time_ms=execution_time_ms,
        )

    return _make_result


class TestStrykerExporterSchemaCompliance:
    """Tests that output complies with mutation-testing-report-schema."""

    def test_produces_valid_json(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        json_str = exporter.to_json(score)

        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_includes_schema_version(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'schemaVersion' in data
        assert data['schemaVersion'] == '1.0'

    def test_includes_thresholds(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'thresholds' in data
        assert 'high' in data['thresholds']
        assert 'low' in data['thresholds']
        assert isinstance(data['thresholds']['high'], int)
        assert isinstance(data['thresholds']['low'], int)

    def test_includes_files_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'files' in data
        assert 'src/auth.py' in data['files']


class TestStrykerExporterFileFormat:
    """Tests for per-file format in Stryker schema."""

    def test_file_includes_language(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert data['files']['src/auth.py']['language'] == 'python'

    def test_file_includes_mutants_array(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'mutants' in data['files']['src/auth.py']
        assert isinstance(data['files']['src/auth.py']['mutants'], list)
        assert len(data['files']['src/auth.py']['mutants']) == 1


class TestStrykerExporterMutantFormat:
    """Tests for individual mutant format in Stryker schema."""

    def test_mutant_includes_id(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'id' in mutant
        assert mutant['id'] == 'g001'

    def test_mutant_includes_mutator_name(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, operator_name='comparison')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'mutatorName' in mutant
        assert mutant['mutatorName'] == 'comparison'

    def test_mutant_includes_location(self, make_gremlin):
        gremlin = make_gremlin(file_path='test.py', line_number=10, column_offset=4)
        result = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)
        score = MutationScore.from_results([result])
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'location' in mutant
        assert 'start' in mutant['location']
        assert mutant['location']['start']['line'] == 10
        assert mutant['location']['start']['column'] == 4

    def test_mutant_includes_description(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, description='>= to >')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'description' in mutant
        assert mutant['description'] == '>= to >'


class TestStrykerExporterStatus:
    """Tests for status mapping from gremlin status to Stryker status."""

    @pytest.mark.parametrize(
        ('gremlin_status', 'stryker_status'),
        [
            (GremlinResultStatus.ZAPPED, 'Killed'),
            (GremlinResultStatus.SURVIVED, 'Survived'),
            (GremlinResultStatus.TIMEOUT, 'Timeout'),
            (GremlinResultStatus.ERROR, 'RuntimeError'),
        ],
    )
    def test_maps_status_correctly(self, make_result, gremlin_status, stryker_status):
        results = [make_result(gremlin_status)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert mutant['status'] == stryker_status


class TestStrykerExporterOptionalFields:
    """Tests for optional fields in Stryker schema."""

    def test_includes_killed_by_when_test_zapped(self, make_result):
        results = [
            make_result(
                GremlinResultStatus.ZAPPED,
                killing_test='test_auth::test_login_validates_age',
            )
        ]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'killedBy' in mutant
        assert mutant['killedBy'] == ['test_auth::test_login_validates_age']

    def test_excludes_killed_by_when_survived(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'killedBy' not in mutant

    def test_includes_duration_when_available(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, execution_time_ms=123.45)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'duration' in mutant
        assert mutant['duration'] == 123

    def test_excludes_duration_when_not_available(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, execution_time_ms=None)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'duration' not in mutant


class TestStrykerExporterFileOutput:
    """Tests for writing Stryker format to file."""

    def test_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()
        output_file = tmp_path / 'mutation.json'

        exporter.write_report(score, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert 'schemaVersion' in data


class TestStrykerExporterFrameworkInfo:
    """Tests for optional framework metadata."""

    def test_includes_framework_info(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'framework' in data
        assert data['framework']['name'] == 'pytest-gremlins'
        assert 'version' in data['framework']


class TestStrykerExporterMutationScoreOnly:
    """Tests for simple mutation score export (for badge only)."""

    def test_exports_score_only_format(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        json_str = exporter.to_score_only_json(score)
        data = json.loads(json_str)

        assert 'mutationScore' in data
        assert data['mutationScore'] == 50.0
