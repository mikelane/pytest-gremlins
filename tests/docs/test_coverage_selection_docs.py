"""Drift check: the docs describe coverage-guided test selection order and early exit (issue #415)."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / 'docs'
ARCHITECTURE_PAGE = DOCS_DIR / 'architecture' / 'coverage-guidance.md'
GUIDE_DIR = DOCS_DIR / 'guide'


def _section(text: str, heading: str) -> str:
    match = re.search(rf'^## {re.escape(heading)}\n(.*?)(?=^## |\Z)', text, re.S | re.M)
    assert match is not None
    return match.group(1)


@pytest.mark.medium
class DescribeCoverageSelectionDocumentation:
    def it_points_gremlin_explain_readers_to_a_section_that_documents_it(self) -> None:
        text = ARCHITECTURE_PAGE.read_text()
        link = re.search(r'`--gremlin-explain` under \[([^\]]+)\]\(#([^)]+)\)', text)

        assert link is not None
        heading = link.group(1)
        assert '--gremlin-explain' in _section(text, heading)

    def it_states_the_priority_order_early_exit_rule_under_docs_guide(self) -> None:
        pages = [
            page
            for page in GUIDE_DIR.rglob('*.md')
            if re.search(r'covering test.{0,400}first fail', page.read_text(), re.I | re.S)
        ]

        assert pages

    def it_says_batch_mode_runs_the_union_of_covering_tests(self) -> None:
        text = ARCHITECTURE_PAGE.read_text()
        section = text[text.index('#### Order and early exit') : text.index('### The Math')]

        assert '--gremlin-batch' in section

    def it_says_tests_without_node_ids_are_dropped_from_the_covering_set(self) -> None:
        text = ARCHITECTURE_PAGE.read_text()
        section = text[text.index('#### Order and early exit') : text.index('### The Math')]

        assert 'node id' in section
