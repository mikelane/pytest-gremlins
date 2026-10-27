"""Drift check: the guides describe the nodes a custom operator is offered, including calls (issue #698)."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

GUIDE_DIR = Path(__file__).resolve().parents[2] / 'docs' / 'guide'


@pytest.mark.medium
class DescribeCustomOperatorNodeDocumentation:
    def it_does_not_tell_users_method_calls_produce_no_gremlins(self):
        text = (GUIDE_DIR / 'operators.md').read_text()

        assert 'produces no gremlins today' not in text

    def it_lists_calls_among_the_nodes_offered_in_the_operators_guide(self):
        text = (GUIDE_DIR / 'operators.md').read_text()
        paragraph = text[text.index('A custom operator is offered') :]
        paragraph = paragraph[: paragraph.index('\n\n')]

        assert 'call' in paragraph

    def it_lists_calls_among_the_nodes_offered_in_the_keep_can_mutate_fast_section(self):
        text = (GUIDE_DIR / 'extensibility.md').read_text()
        section = text[text.index('### Keep can_mutate() Fast') : text.index('### Always Deep Copy')]

        assert re.search(r'\(every comparison, operation, literal and\s+`return`\)', section) is None
        assert 'call' in section.split('```')[0]
