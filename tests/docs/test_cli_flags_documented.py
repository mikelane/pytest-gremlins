"""Drift check 1a: the documented command-line flags are exactly the flags the plugin registers."""

from __future__ import annotations

import pytest

from .docs_facts import (
    HIDDEN_OPTIONS,
    documented_flags,
    flags_mentioned_in_docs,
    hidden_flags,
    registered_flags,
)


@pytest.mark.medium
class DescribeCliFlagDocumentation:
    """The options reference in configuration.md matches the real parser."""

    def it_documents_every_registered_flag_in_the_options_tables(self):
        undocumented = registered_flags() - HIDDEN_OPTIONS - documented_flags()

        assert not undocumented, (
            f'Flags registered in plugin.py but missing from docs/guide/configuration.md: {sorted(undocumented)}'
        )

    def it_lists_every_hidden_option_in_the_exemption_set(self):
        unlisted = hidden_flags() - HIDDEN_OPTIONS

        assert not unlisted, f'Hidden options must be listed in HIDDEN_OPTIONS: {sorted(unlisted)}'

    def it_mentions_only_flags_the_plugin_registers(self):
        registered = registered_flags()

        invented = {flag: pages for flag, pages in flags_mentioned_in_docs().items() if flag not in registered}

        assert not invented, f'Docs mention flags the plugin does not register: {invented}'

    def it_documents_no_flag_in_the_options_tables_that_the_plugin_lacks(self):
        stale = documented_flags() - registered_flags()

        assert not stale, f'docs/guide/configuration.md documents flags the plugin does not register: {sorted(stale)}'
