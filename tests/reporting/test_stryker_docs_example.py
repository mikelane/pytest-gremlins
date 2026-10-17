"""The Stryker report example in the user guide must stay valid against the vendored schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((Path(__file__).parent / 'data' / 'mutation-testing-report-schema.json').read_text())
FORMAT_HEADING = '#### Stryker Dashboard Format (mutation-testing-report-schema)'


def _documented_example() -> dict:
    guide = (REPO_ROOT / 'docs' / 'guide' / 'reports.md').read_text(encoding='utf-8')
    section = guide.split(FORMAT_HEADING, 1)[1]
    return json.loads(section.split('```json', 1)[1].split('```', 1)[0])


@pytest.mark.medium
class DescribeStrykerDocsExample:
    def it_validates_against_the_report_schema(self):
        jsonschema.validate(_documented_example(), SCHEMA)

    def it_shows_the_source_of_each_file(self):
        example = _documented_example()

        assert all('source' in entry for entry in example['files'].values())
