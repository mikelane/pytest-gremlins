"""Unit tests for the default comparison behind drift check 1c."""

from __future__ import annotations

import pytest

from .default_facts import (
    default_comment_mismatches,
    default_mismatches,
)


@pytest.mark.small
class DescribeDefaultMismatches:
    """An option with no code default must be documented with the phrase registered for that option."""

    def it_accepts_the_phrase_registered_for_the_option(self):
        assert default_mismatches({'--max-pardons': 'disabled'}, {'--max-pardons': None}) == []

    def it_rejects_a_phrase_registered_for_a_different_option(self):
        problems = default_mismatches({'--max-pardons': 'auto-discovered'}, {'--max-pardons': None})

        assert problems == [
            "--max-pardons: documented 'auto-discovered', but the code has no default "
            "(use 'disabled'; register a phrase in UNSET_PHRASE_BY_NAME if none)"
        ]

    def it_rejects_an_option_with_no_registered_phrase(self):
        problems = default_mismatches({'--invented': 'none'}, {'--invented': None})

        assert problems == [
            "--invented: documented 'none', but the code has no default "
            '(use None; register a phrase in UNSET_PHRASE_BY_NAME if none)'
        ]

    def it_accepts_a_documented_value_equal_to_the_code_default(self):
        assert default_mismatches({'--gremlin-batch-size': '`10`'}, {'--gremlin-batch-size': '10'}) == []

    def it_rejects_a_documented_value_that_differs_from_the_code_default(self):
        problems = default_mismatches({'--gremlin-batch-size': '`11`'}, {'--gremlin-batch-size': '10'})

        assert problems == ["--gremlin-batch-size: documented '11', code default '10'"]


@pytest.mark.small
class DescribeDefaultCommentPrefixMatch:
    """A TOML Default comment that states a different number must not pass because it starts with the right digits."""

    def it_rejects_a_comment_stating_300_when_the_table_says_30(self):
        assert default_comment_mismatches({'mutant_timeout': '300'}, {'mutant_timeout': '`30`'}) != []

    def it_rejects_a_comment_stating_1200_when_the_table_says_120(self):
        assert default_comment_mismatches({'coverage_timeout': '1200'}, {'coverage_timeout': '`120`'}) != []
