"""Stryker export locations and source for files the plugin decodes with ``tokenize.open``.

Each test instruments a real file the way the plugin does (``tokenize.open`` then
``transform_source``) and checks the exported 1-based [start, end) range against the exported
``source`` and the mutated AST node.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import tokenize
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import StrykerExporter

if TYPE_CHECKING:
    from pytest_gremlins.instrumentation.gremlin import Gremlin

BOM = b'\xef\xbb\xbf'
LATIN1_SOURCE = "# -*- coding: latin-1 -*-\ndef n(a):\n    s = 'é'; return a + 1\n"


def _instrument(path: Path) -> tuple[str, list[Gremlin]]:
    with tokenize.open(str(path)) as stream:
        decoded = stream.read()
    gremlins, _tree = transform_source(decoded, str(path))
    return decoded, gremlins


def _export_file(path: Path, gremlins: list[Gremlin]) -> dict:
    results = [GremlinResult(gremlin=g, status=GremlinResultStatus.SURVIVED) for g in gremlins]
    return json.loads(StrykerExporter().to_json(MutationScore.from_results(results)))['files'][str(path)]


def _exported_text(entry: dict, mutant: dict) -> str:
    start, end = mutant['location']['start'], mutant['location']['end']
    line = entry['source'].splitlines()[start['line'] - 1]
    return line[start['column'] - 1 : end['column'] - 1]


@pytest.mark.medium
class DescribeBomFiles:
    def it_locates_a_line_one_mutant_in_a_utf8_bom_file(self, tmp_path):
        path = tmp_path / 'bom.py'
        path.write_bytes(BOM + b'def g(x): return x + 1\n')
        decoded, gremlins = _instrument(path)
        entry = _export_file(path, gremlins)
        node = next(g.original_node for g in gremlins if g.line_number == 1)

        mutant = next(m for m in entry['mutants'] if m['location']['start']['line'] == 1)

        assert _exported_text(entry, mutant) == ast.get_source_segment(decoded, node)

    def it_exports_the_source_of_a_bom_file_without_the_bom(self, tmp_path):
        path = tmp_path / 'bom.py'
        path.write_bytes(BOM + b'def g(x): return x + 1\n')
        _decoded, gremlins = _instrument(path)

        entry = _export_file(path, gremlins)

        assert entry['source'] == 'def g(x): return x + 1\n'


@pytest.mark.medium
class DescribePep263Files:
    def it_exports_the_source_of_a_latin1_declared_file(self, tmp_path):
        path = tmp_path / 'latin1.py'
        path.write_bytes(LATIN1_SOURCE.encode('latin-1'))
        decoded, gremlins = _instrument(path)

        entry = _export_file(path, gremlins)

        assert entry['source'] == decoded

    def it_counts_columns_in_characters_for_a_latin1_declared_file(self, tmp_path):
        path = tmp_path / 'latin1.py'
        path.write_bytes(LATIN1_SOURCE.encode('latin-1'))
        _decoded, gremlins = _instrument(path)

        entry = _export_file(path, gremlins)

        # "    s = 'é'; return a + 1": the BinOp 'a + 1' starts at character index 20 -> column 21.
        assert entry['mutants'][0]['location']['start'] == {'line': 3, 'column': 21}


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
