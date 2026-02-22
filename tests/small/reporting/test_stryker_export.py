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
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
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


class DescribeStrykerExporterSchemaCompliance:
    """Tests that output complies with mutation-testing-report-schema."""

    def it_produces_valid_json(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        json_str = exporter.to_json(score)

        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def it_includes_schema_version(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'schemaVersion' in data
        assert data['schemaVersion'] == '1.0'

    def it_includes_thresholds(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'thresholds' in data
        assert 'high' in data['thresholds']
        assert 'low' in data['thresholds']
        assert isinstance(data['thresholds']['high'], int)
        assert isinstance(data['thresholds']['low'], int)

    def it_includes_files_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'files' in data
        assert 'src/auth.py' in data['files']


class DescribeStrykerExporterFileFormat:
    """Tests for per-file format in Stryker schema."""

    def it_includes_language_in_file_output(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert data['files']['src/auth.py']['language'] == 'python'

    def it_includes_mutants_array_in_file_output(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'mutants' in data['files']['src/auth.py']
        assert isinstance(data['files']['src/auth.py']['mutants'], list)
        assert len(data['files']['src/auth.py']['mutants']) == 1


class DescribeStrykerExporterMutantFormat:
    """Tests for individual mutant format in Stryker schema."""

    def it_mutant_includes_id(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'id' in mutant
        assert mutant['id'] == 'g001'

    def it_mutant_includes_mutator_name(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, operator_name='comparison')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'mutatorName' in mutant
        assert mutant['mutatorName'] == 'comparison'

    def it_mutant_includes_location(self, make_gremlin):
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

    def it_mutant_location_omits_end_when_end_lineno_is_none(self, make_gremlin) -> None:
        """_build_location omits 'end' key when AST node has no end_lineno."""
        gremlin = make_gremlin(file_path='test.py', line_number=5, column_offset=2)
        gremlin.original_node.end_lineno = None
        result = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)
        score = MutationScore.from_results([result])
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'end' not in mutant['location']


    def it_mutant_includes_description(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, description='>= to >')]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'description' in mutant
        assert mutant['description'] == '>= to >'


class DescribeStrykerExporterStatus:
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
    def it_maps_status_correctly(self, make_result, gremlin_status, stryker_status):
        results = [make_result(gremlin_status)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert mutant['status'] == stryker_status


class DescribeStrykerExporterOptionalFields:
    """Tests for optional fields in Stryker schema."""

    def it_includes_killed_by_when_test_zapped(self, make_result):
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

    def it_excludes_killed_by_when_survived(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'killedBy' not in mutant

    def it_includes_duration_when_available(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, execution_time_ms=123.45)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'duration' in mutant
        assert mutant['duration'] == 123

    def it_excludes_duration_when_not_available(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED, execution_time_ms=None)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))
        mutant = data['files']['test.py']['mutants'][0]

        assert 'duration' not in mutant


class DescribeStrykerExporterFileOutput:
    """Tests for writing Stryker format to file."""

    def it_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()
        output_file = tmp_path / 'mutation.json'

        exporter.write_report(score, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert 'schemaVersion' in data


class DescribeStrykerExporterFrameworkInfo:
    """Tests for optional framework metadata."""

    def it_includes_framework_info(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = StrykerExporter()

        data = json.loads(exporter.to_json(score))

        assert 'framework' in data
        assert data['framework']['name'] == 'pytest-gremlins'
        assert 'version' in data['framework']


class DescribeStrykerExporterMutationScoreOnly:
    """Tests for simple mutation score export (for badge only)."""

    def it_exports_score_only_format(self, make_result):
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
