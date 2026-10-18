"""Stryker export type names and UTF-16 column counting.

The report schema calls ``{line, column}`` a Position and ``{start, end}`` a Location. The
mutation-testing-elements viewer indexes source with JS string indices, which are UTF-16 code
units, so a character outside the BMP (an emoji) occupies two columns.
"""

from __future__ import annotations

import json
from typing import get_type_hints

import pytest

from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.stryker_export import (
    StrykerExporter,
    utf16_column,
)
from pytest_gremlins.reporting.types import (
    StrykerLocation,
    StrykerMutant,
    StrykerPosition,
)

EMOJI = '\U0001f600'
FILE_PATH = 'positions.py'


def _location_for(make_gremlin, source: str, **gremlin_args) -> dict:
    gremlin = make_gremlin(file_path=FILE_PATH, **gremlin_args)
    exporter = StrykerExporter(source_reader=lambda _path: source)
    score = MutationScore.from_results([GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)])
    return json.loads(exporter.to_json(score))['files'][FILE_PATH]['mutants'][0]['location']


@pytest.mark.small
class DescribeSchemaTypeNames:
    def it_names_the_line_and_column_pair_a_position(self):
        assert set(get_type_hints(StrykerPosition)) == {'line', 'column'}

    def it_names_the_start_and_end_pair_a_location(self):
        assert set(get_type_hints(StrykerLocation)) == {'start', 'end'}

    def it_types_a_mutant_location_as_a_location(self):
        assert get_type_hints(StrykerMutant)['location'] is StrykerLocation


@pytest.mark.small
class DescribeUtf16Column:
    def it_leaves_ascii_columns_unchanged(self):
        assert utf16_column(['x = a + 1'], 1, 4) == 4

    def it_counts_a_bmp_character_as_one_unit(self):
        # "s = 'é'; x": the AST byte offset 9 is character 8.
        assert utf16_column(["s = 'é'; x"], 1, 9) == 8

    def it_counts_an_astral_character_as_two_units(self):
        # "s = '😀'; x": the emoji is 4 UTF-8 bytes, 1 code point, 2 UTF-16 units; 'x' is at byte 12.
        assert utf16_column([f"s = '{EMOJI}'; x"], 1, 12) == 10

    def it_returns_the_byte_offset_when_the_line_is_unavailable(self):
        assert utf16_column([], 1, 4) == 4


@pytest.mark.small
class DescribeExportedColumns:
    def it_shifts_columns_after_an_astral_character_by_two_units(self, make_gremlin):
        source = f"s = '{EMOJI}'; a + 1"
        byte_start = len(f"s = '{EMOJI}'; ".encode())

        location = _location_for(make_gremlin, source, column_offset=byte_start, end_column_offset=byte_start + 5)

        # The prefix is 9 code points but 10 UTF-16 units, so the 1-based column is 11.
        assert location == {'start': {'line': 1, 'column': 11}, 'end': {'line': 1, 'column': 16}}

    def it_counts_an_astral_character_inside_the_range_as_two_units(self, make_gremlin):
        source = f"'{EMOJI}'"

        location = _location_for(make_gremlin, source, column_offset=0, end_column_offset=len(source.encode()))

        assert location == {'start': {'line': 1, 'column': 1}, 'end': {'line': 1, 'column': 5}}

    def it_keeps_bmp_non_ascii_columns_one_unit_per_character(self, make_gremlin):
        source = "s = 'é'; a + 1"
        byte_start = len("s = 'é'; ".encode())

        location = _location_for(make_gremlin, source, column_offset=byte_start, end_column_offset=byte_start + 5)

        assert location['start'] == {'line': 1, 'column': 10}
