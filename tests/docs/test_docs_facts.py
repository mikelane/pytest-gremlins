"""The helpers that read facts from the plugin and the docs notice drift and report it clearly."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import pytest_addoption as real_hook

from . import docs_facts
from .docs_facts import (
    quoted_messages,
    registered_flags,
)


@pytest.mark.medium
class DescribeRegisteredOptions:
    """The option list covers every group the plugin's hook registers into."""

    def it_includes_an_option_added_with_parser_addoption(self, monkeypatch: pytest.MonkeyPatch):
        def hook_adding_an_anonymous_option(parser: pytest.Parser) -> None:
            real_hook(parser)
            parser.addoption('--gremlin-example', action='store_true', help='an undocumented option')

        monkeypatch.setattr(docs_facts, 'pytest_addoption', hook_adding_an_anonymous_option)

        assert '--gremlin-example' in registered_flags()

    def it_includes_an_option_added_to_another_named_group(self, monkeypatch: pytest.MonkeyPatch):
        def hook_adding_a_grouped_option(parser: pytest.Parser) -> None:
            real_hook(parser)
            parser.getgroup('other').addoption('--gremlin-other', action='store_true', help='another group')

        monkeypatch.setattr(docs_facts, 'pytest_addoption', hook_adding_a_grouped_option)

        assert '--gremlin-other' in registered_flags()

    def it_still_includes_the_gremlins_group_options(self):
        assert '--gremlins' in registered_flags()


@pytest.mark.medium
class DescribeQuotedMessages:
    """A message quoted as pytest prints a usage error is checked like any other."""

    def it_finds_a_message_quoted_after_the_error_prefix(self, tmp_path: Path):
        (tmp_path / 'page.md').write_text(
            '```text\n$ pytest --gremlins\nERROR: pytest-gremlins: this message does not exist\n```\n',
            encoding='utf-8',
        )

        assert [quoted.text for quoted in quoted_messages(tmp_path)] == ['pytest-gremlins: this message does not exist']
