"""Stryker export locations and source for files the plugin decodes with ``tokenize.open``.

Each test instruments a real file the way the plugin does (``tokenize.open`` then
``transform_source``) and checks the exported 1-based [start, end) range against the exported
``source`` and the mutated AST node.
"""

from __future__ import annotations

import ast
import json
import logging
import tokenize
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import (
    StrykerExporter,
    read_source,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.instrumentation.gremlin import Gremlin

UTF8_BOM = b'\xef\xbb\xbf'
LATIN1_SOURCE = "# -*- coding: latin-1 -*-\ndef n(a):\n    s = 'é'; return a + 1\n"


def _instrument(path: Path) -> tuple[str, list[Gremlin]]:
    with tokenize.open(str(path)) as stream:
        decoded_source = stream.read()
    gremlins, _tree = transform_source(decoded_source, str(path))
    return decoded_source, gremlins


def _export_file(path: Path, gremlins: list[Gremlin]) -> dict[str, Any]:
    results = [GremlinResult(gremlin=g, status=GremlinResultStatus.SURVIVED) for g in gremlins]
    return cast(
        'dict[str, Any]', json.loads(StrykerExporter().to_json(MutationScore.from_results(results)))['files'][str(path)]
    )


def _exported_text(file_report: dict[str, Any], mutant: dict[str, Any]) -> str:
    start, end = mutant['location']['start'], mutant['location']['end']
    line = file_report['source'].splitlines()[start['line'] - 1]
    return cast('str', line[start['column'] - 1 : end['column'] - 1])


@pytest.mark.medium
class DescribeBomFiles:
    def it_locates_a_line_one_mutant_in_a_utf8_bom_file(self, tmp_path):
        path = tmp_path / 'bom.py'
        path.write_bytes(UTF8_BOM + b'def g(x): return x + 1\n')
        decoded_source, gremlins = _instrument(path)
        file_report = _export_file(path, gremlins)
        node = gremlins[0].original_node

        mutant = file_report['mutants'][0]

        assert mutant['location']['start']['line'] == 1
        assert _exported_text(file_report, mutant) == ast.get_source_segment(decoded_source, node)

    def it_exports_the_source_of_a_bom_file_without_the_bom(self, tmp_path):
        path = tmp_path / 'bom.py'
        path.write_bytes(UTF8_BOM + b'def g(x): return x + 1\n')
        _decoded_source, gremlins = _instrument(path)

        file_report = _export_file(path, gremlins)

        assert file_report['source'] == 'def g(x): return x + 1\n'


@pytest.mark.medium
class DescribePep263Files:
    def it_exports_the_source_of_a_latin1_declared_file(self, tmp_path):
        path = tmp_path / 'latin1.py'
        path.write_bytes(LATIN1_SOURCE.encode('latin-1'))
        decoded_source, gremlins = _instrument(path)

        file_report = _export_file(path, gremlins)

        assert file_report['source'] == decoded_source

    def it_counts_columns_in_characters_for_a_latin1_declared_file(self, tmp_path):
        path = tmp_path / 'latin1.py'
        path.write_bytes(LATIN1_SOURCE.encode('latin-1'))
        _decoded_source, gremlins = _instrument(path)

        file_report = _export_file(path, gremlins)

        # "    s = 'é'; return a + 1": the BinOp 'a + 1' starts at character index 20 -> column 21.
        assert file_report['mutants'][0]['location']['start'] == {'line': 3, 'column': 21}


@pytest.mark.small
class DescribeUnreadableSourceFallback:
    def it_keeps_the_ast_columns_on_line_one_when_the_source_is_unavailable(self, make_gremlin):
        gremlin = make_gremlin(line_number=1, column_offset=10, end_line_number=1, end_column_offset=16)
        exporter = StrykerExporter(source_reader=lambda _path: '')

        report = json.loads(
            exporter.to_json(
                MutationScore.from_results([GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)])
            )
        )

        location = report['files']['test.py']['mutants'][0]['location']
        assert location == {'start': {'line': 1, 'column': 11}, 'end': {'line': 1, 'column': 17}}


@pytest.mark.small
class DescribeUnreadableSourceWarning:
    def it_warns_naming_the_path_and_exports_empty_source(self, monkeypatch, caplog):
        def fail_to_open(_path: str) -> None:
            raise PermissionError('denied')

        monkeypatch.setattr('pytest_gremlins.reporting.stryker_export.tokenize.open', fail_to_open)

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.reporting.stryker_export'):
            source = read_source('pkg/locked.py')

        assert source == ''
        assert [(r.levelno, 'pkg/locked.py' in r.getMessage()) for r in caplog.records] == [(logging.WARNING, True)]


@pytest.mark.medium
class DescribeNonTextCodecCookie:
    @pytest.mark.parametrize('codec', ['rot13', 'hex', 'base64', 'undefined'])
    def it_exports_empty_source_when_the_cookie_names_a_non_text_codec(self, tmp_path, codec):
        path = tmp_path / 'cookie.py'
        path.write_text(f'# coding: {codec}\nx = 1\n', encoding='ascii')

        assert read_source(str(path)) == ''
