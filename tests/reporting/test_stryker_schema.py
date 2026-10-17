"""Validates the Stryker export against the official mutation-testing-report-schema.

The schema is vendored from
https://github.com/stryker-mutator/mutation-testing-elements (packages/report-schema) so the
test needs no network. It accepts report versions 1.x and 2.x, which covers the ``1.0`` the
exporter declares.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import StrykerExporter

SCHEMA = json.loads((Path(__file__).parent / 'data' / 'mutation-testing-report-schema.json').read_text())


def _export(*results: GremlinResult, exporter: StrykerExporter | None = None) -> dict:
    exporter = exporter or StrykerExporter(source_reader=lambda _path: '')
    return json.loads(exporter.to_json(MutationScore.from_results(list(results))))


def _export_reading_disk(result: GremlinResult) -> dict:
    return _export(result, exporter=StrykerExporter())


@pytest.mark.small
class DescribeSchemaValidity:
    @pytest.mark.parametrize('status', list(GremlinResultStatus))
    def it_validates_a_report_for_every_status(self, make_result, status):
        report = _export(make_result(status))

        jsonschema.validate(report, SCHEMA)

    def it_validates_a_report_with_no_results(self):
        report = _export()

        jsonschema.validate(report, SCHEMA)

    def it_validates_when_the_node_has_no_end_position(self, make_gremlin):
        gremlin = make_gremlin()
        gremlin.original_node.end_lineno = None
        gremlin.original_node.end_col_offset = None

        report = _export(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED))

        jsonschema.validate(report, SCHEMA)


@pytest.mark.medium
class DescribeFileSource:
    def it_uses_an_injected_source_reader(self, make_result):
        exporter = StrykerExporter(source_reader=lambda path: f'# {path}')

        report = _export(make_result(), exporter=exporter)

        assert report['files']['test.py']['source'] == '# test.py'

    def it_includes_the_original_source_of_each_file(self, make_gremlin, tmp_path):
        source_file = tmp_path / 'module.py'
        source_file.write_text('x >= 0\n')
        gremlin = make_gremlin(file_path=str(source_file))

        report = _export_reading_disk(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        assert report['files'][str(source_file)]['source'] == 'x >= 0\n'

    def it_exports_an_empty_source_when_the_file_cannot_be_read(self, make_gremlin, tmp_path):
        gremlin = make_gremlin(file_path=str(tmp_path / 'missing.py'))

        report = _export_reading_disk(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        assert report['files'][str(tmp_path / 'missing.py')]['source'] == ''

    def it_decodes_source_as_utf8(self, make_gremlin, tmp_path):
        source_file = tmp_path / 'unicode.py'
        source_file.write_text("name = 'café'\n", encoding='utf-8')
        gremlin = make_gremlin(file_path=str(source_file))

        report = _export_reading_disk(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        assert report['files'][str(source_file)]['source'] == "name = 'café'\n"


@pytest.mark.small
class DescribeOneBasedPositions:
    def it_converts_the_zero_based_ast_start_column_to_one_based(self, make_gremlin):
        gremlin = make_gremlin(line_number=10, column_offset=0, end_line_number=10, end_column_offset=6)

        report = _export(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        start = report['files']['test.py']['mutants'][0]['location']['start']
        assert start == {'line': 10, 'column': 1}

    def it_converts_the_ast_end_column_to_one_based(self, make_gremlin):
        gremlin = make_gremlin(line_number=10, column_offset=4, end_line_number=10, end_column_offset=10)

        report = _export(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        end = report['files']['test.py']['mutants'][0]['location']['end']
        assert end == {'line': 10, 'column': 11}

    def it_falls_back_to_the_start_position_when_the_node_has_no_end(self, make_gremlin):
        gremlin = make_gremlin(line_number=5, column_offset=2)
        gremlin.original_node.end_lineno = None
        gremlin.original_node.end_col_offset = None

        report = _export(GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED))

        location = report['files']['test.py']['mutants'][0]['location']
        assert location['end'] == location['start'] == {'line': 5, 'column': 3}
