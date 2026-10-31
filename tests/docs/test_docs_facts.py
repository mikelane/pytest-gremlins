"""The helpers that read facts from the plugin and the docs notice drift and report it clearly."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import pytest_addoption as real_hook

from . import docs_facts
from .docs_facts import (
    DocsFormatError,
    default_cells,
    pytest_gremlins_toml_blocks,
    quoted_messages,
    registered_flags,
    toml_default_comments,
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


@pytest.mark.medium
class DescribeTomlBlocks:
    """A TOML block that does not parse is reported with its page and line."""

    def it_names_the_page_and_line_of_a_block_that_does_not_parse(self, tmp_path: Path):
        page = tmp_path / 'configuration.md'
        page.write_text('intro\n\n```toml\n[tool.pytest-gremlins]\nworkers = ...\n```\n', encoding='utf-8')

        with pytest.raises(DocsFormatError, match=r'configuration\.md:3: .*TOML'):
            pytest_gremlins_toml_blocks(page)


@pytest.mark.medium
class DescribeDefaultCells:
    """The Default column is found by its header, wherever it sits."""

    def it_reads_a_table_whose_default_column_is_second(self, tmp_path: Path):
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Key | Default | Description |\n|---|---|---|\n| `batch_size` | `99` | batch size |\n',
            encoding='utf-8',
        )

        assert default_cells(page) == {'batch_size': '`99`'}

    def it_names_the_page_and_line_of_a_row_too_short_to_have_a_default(self, tmp_path: Path):
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Key | Description | Default |\n|---|---|---|\n| `batch_size` | batch size |\n', encoding='utf-8'
        )

        with pytest.raises(DocsFormatError, match=r'configuration\.md:3: .*Default'):
            default_cells(page)


@pytest.mark.medium
class DescribeTomlDefaultCommentAttribution:
    """A Default comment belongs to the assignment directly below it, not to whichever key comes next."""

    def it_does_not_carry_an_orphan_comment_over_a_commented_out_key(self, tmp_path: Path):
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: 10\n# batch_size = 20\n\ncache = true\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {}
