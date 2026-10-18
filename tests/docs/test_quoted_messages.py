"""Drift check 1d: every ``pytest-gremlins:`` message quoted in the docs is one the code can emit."""

from __future__ import annotations

import pytest

from .docs_facts import (
    REPO_ROOT,
    quoted_messages,
)
from .emitted_messages import (
    line_is_emittable,
    message_templates_under,
)

SOURCE_ROOT = REPO_ROOT / 'src' / 'pytest_gremlins'
# Fewer than this many quoted lines or templates means the scan broke, not that the docs and source are clean.
SCAN_SANITY_FLOOR = 10


@pytest.mark.medium
class DescribeQuotedMessages:
    """Messages quoted in fenced docs blocks match the messages in the source."""

    def it_quotes_only_messages_the_plugin_can_emit(self):
        templates = message_templates_under(SOURCE_ROOT)

        invented = [
            f'{quoted.location}: {quoted.text}'
            for quoted in quoted_messages()
            if not line_is_emittable(quoted.text, templates, continues=quoted.continues)
        ]

        assert not invented, 'Docs quote messages the plugin never prints:\n' + '\n'.join(invented)

    def it_finds_the_messages_the_docs_quote(self):
        assert len(quoted_messages()) >= SCAN_SANITY_FLOOR

    def it_finds_message_templates_in_the_source(self):
        assert len(message_templates_under(SOURCE_ROOT)) >= SCAN_SANITY_FLOOR
