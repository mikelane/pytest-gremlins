"""Drift check 1c: the default in each ``Default`` column of configuration.md equals the default in the code.

Format the docs must use in a ``Default`` cell:

* a single backticked literal, such as ``10``, ``false`` or ``"console"``, when the code has a concrete default;
* otherwise the one phrase ``UNSET_PHRASE_BY_NAME`` registers for that option (or the default the option's own help
  text states).

The code default comes from the parser (a non-``None`` argparse default), from a named constant or session field in
``plugin.py``, or, for options whose default is computed, from the ``(default: ...)`` in the option's help text.
"""

from __future__ import annotations

import pytest

from pytest_gremlins.config import CONFIG_KEYS

from .default_facts import (
    CONFIG_KEY_TO_FLAG,
    default_comment_mismatches,
    default_mismatches,
    expected_flag_defaults,
    expected_key_defaults,
    flag_defaults_in_docs,
    key_defaults_in_docs,
    toml_default_comment_mismatches,
)


@pytest.mark.medium
class DescribeDocumentedDefaults:
    """Every default stated in configuration.md is the default the code applies."""

    def it_states_each_flags_code_default_in_the_options_tables(self):
        mismatches = default_mismatches(flag_defaults_in_docs(), expected_flag_defaults())

        assert not mismatches, 'Flag defaults in configuration.md differ from the code:\n' + '\n'.join(mismatches)

    def it_states_each_keys_code_default_in_the_configuration_table(self):
        mismatches = default_mismatches(key_defaults_in_docs(), expected_key_defaults())

        assert not mismatches, 'Key defaults in configuration.md differ from the code:\n' + '\n'.join(mismatches)

    def it_maps_every_config_key_to_the_flag_that_overrides_it(self):
        assert set(CONFIG_KEY_TO_FLAG) == CONFIG_KEYS

    def it_states_in_each_toml_example_the_default_its_table_row_states(self):
        mismatches = toml_default_comment_mismatches()

        assert not mismatches, 'TOML example Default comments differ from the options table:\n' + '\n'.join(mismatches)


@pytest.mark.small
class DescribeDefaultCommentMismatches:
    """A TOML ``# Default:`` comment may add detail after the table's default, but not change it."""

    def it_accepts_a_comment_that_repeats_the_table_default(self):
        assert default_comment_mismatches({'batch_size': '10'}, {'batch_size': '`10`'}) == []

    def it_accepts_a_comment_that_adds_detail_after_the_table_default(self):
        assert default_comment_mismatches({'operators': 'all operators'}, {'operators': 'all'}) == []

    def it_rejects_a_comment_that_differs_from_the_table_default(self):
        problems = default_comment_mismatches({'batch_size': '11'}, {'batch_size': '`10`'})

        assert problems == ['batch_size: the TOML example says "Default: 11", the options table says \'10\'']

    def it_rejects_a_comment_for_a_key_the_table_lacks(self):
        problems = default_comment_mismatches({'invented': '1'}, {})

        assert problems == ['invented: the TOML example says "Default: 1" but the options table has no such key']
