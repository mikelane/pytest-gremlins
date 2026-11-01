"""The Stryker report example in the user guide must stay valid against the vendored schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import (
    Any,
    cast,
)

import jsonschema  # type: ignore[import-untyped]
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((Path(__file__).parent / 'data' / 'mutation-testing-report-schema.json').read_text())
EXAMPLE_MARKER = '<!-- stryker-report-example -->\n```json\n'


def _documented_example() -> dict[str, Any]:
    guide = (REPO_ROOT / 'docs' / 'guide' / 'reports.md').read_text(encoding='utf-8')
    assert guide.count(EXAMPLE_MARKER) == 1, 'docs/guide/reports.md must mark exactly one Stryker example block'
    block = guide.split(EXAMPLE_MARKER, 1)[1]
    return cast('dict[str, Any]', json.loads(block.split('```', 1)[0]))


@pytest.mark.medium
class DescribeStrykerDocsExample:
    def it_validates_against_the_report_schema(self):
        jsonschema.validate(_documented_example(), SCHEMA)

    def it_shows_the_source_of_each_file(self):
        example = _documented_example()

        assert example['files']
        assert all('source' in entry for entry in example['files'].values())
