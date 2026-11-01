"""The helpers that read facts from the plugin and the docs notice drift and report it clearly."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.plugin import pytest_addoption as real_hook

from . import docs_facts
from .docs_facts import (
    CONFIGURATION_PAGE,
    DocsFormatError,
    default_cells,
    documented_flags,
    pytest_gremlins_toml_blocks,
    quoted_messages,
    registered_flags,
    toml_default_comments,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.medium
class DescribeRegisteredOptions:
    """The option list covers every group the plugin's hook registers into."""

    def it_includes_an_option_added_with_parser_addoption(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def hook_adding_an_anonymous_option(parser: pytest.Parser) -> None:
            real_hook(parser)
            parser.addoption('--gremlin-example', action='store_true', help='an undocumented option')

        monkeypatch.setattr(docs_facts, 'pytest_addoption', hook_adding_an_anonymous_option)

        assert '--gremlin-example' in registered_flags()

    def it_includes_an_option_added_to_another_named_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def it_finds_a_message_quoted_after_the_error_prefix(self, tmp_path: Path) -> None:
        (tmp_path / 'page.md').write_text(
            '```text\n$ pytest --gremlins\nERROR: pytest-gremlins: this message does not exist\n```\n',
            encoding='utf-8',
        )

        assert [quoted.text for quoted in quoted_messages(tmp_path)] == ['pytest-gremlins: this message does not exist']


@pytest.mark.medium
class DescribeTomlBlocks:
    """A TOML block that does not parse is reported with its page and line."""

    def it_names_the_page_and_line_of_a_block_that_does_not_parse(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text('intro\n\n```toml\n[tool.pytest-gremlins]\nworkers = ...\n```\n', encoding='utf-8')

        with pytest.raises(DocsFormatError, match=r'configuration\.md:3: .*TOML'):
            pytest_gremlins_toml_blocks(page)

    def it_reads_a_block_fenced_with_tildes(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text('~~~toml\n[tool.pytest-gremlins]\nworkers = 2\n~~~\n', encoding='utf-8')

        assert pytest_gremlins_toml_blocks(page) == [{'workers': 2}]

    def it_reads_a_block_whose_language_tag_is_uppercase(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text('```TOML\n[tool.pytest-gremlins]\nworkers = 2\n```\n', encoding='utf-8')

        assert pytest_gremlins_toml_blocks(page) == [{'workers': 2}]

    def it_keeps_a_backtick_line_inside_a_tilde_fence_as_block_content(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '~~~toml\n[tool.pytest-gremlins]\n```\nworkers = 2\n~~~\n',
            encoding='utf-8',
        )

        with pytest.raises(DocsFormatError, match=r'configuration\.md:1: .*TOML'):
            pytest_gremlins_toml_blocks(page)


@pytest.mark.medium
class DescribeDefaultCells:
    """The Default column is found by its header, wherever it sits."""

    def it_reads_a_table_whose_default_column_is_second(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Key | Default | Description |\n|---|---|---|\n| `batch_size` | `99` | batch size |\n',
            encoding='utf-8',
        )

        assert default_cells(page) == {'batch_size': '`99`'}

    def it_names_the_page_and_line_of_a_row_too_short_to_have_a_default(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Key | Description | Default |\n|---|---|---|\n| `batch_size` | batch size |\n', encoding='utf-8'
        )

        with pytest.raises(DocsFormatError, match=r'configuration\.md:3: .*Default'):
            default_cells(page)

    def it_names_the_page_and_line_of_a_name_in_two_default_tables(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Key | Default |\n|---|---|\n| `batch_size` | `10` |\n\n'
            '| Key | Default |\n|---|---|\n| `batch_size` | `20` |\n',
            encoding='utf-8',
        )

        with pytest.raises(DocsFormatError, match=r'configuration\.md:7: .*batch_size.*line 3'):
            default_cells(page)


@pytest.mark.medium
class DescribeDocumentedFlags:
    """A flag counts as documented only in a table that states its default."""

    def it_does_not_count_a_flag_in_a_table_without_a_default_column(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text('| Flag | Description |\n|---|---|\n| `--gremlin-example` | an example |\n', encoding='utf-8')

        assert documented_flags(page) == frozenset()

    def it_counts_a_flag_in_a_table_with_a_default_column(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '| Flag | Default | Description |\n|---|---|---|\n| `--gremlin-example` | `false` | an example |\n',
            encoding='utf-8',
        )

        assert documented_flags(page) == frozenset({'--gremlin-example'})


@pytest.mark.medium
class DescribeTomlDefaultCommentAttribution:
    """A Default comment belongs to the assignment directly below it, not to whichever key comes next."""

    def it_does_not_carry_an_orphan_comment_over_a_commented_out_key(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: 10\n# batch_size = 20\n\ncache = true\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {}

    def it_attributes_a_default_comment_that_more_comment_lines_follow(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: []\n# Test files are skipped.\nexclude = []\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {'exclude': '[]'}

    def it_attributes_a_default_comment_that_wraps_onto_a_second_line(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: not set (one at a time unless\n'
            '# -n N is passed)\nworkers = "auto"\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {'workers': 'not set (one at a time unless'}

    def it_attributes_a_default_comment_inside_an_indented_block(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '=== "pyproject.toml"\n\n    ```toml\n    [tool.pytest-gremlins]\n    # Default: 10\n    batch_size = 10\n'
            '    ```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {'batch_size': '10'}

    def it_does_not_carry_an_orphan_comment_past_a_blank_line_after_another_comment(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: auto\n\n# Enable cache\ncache = true\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {}

    def it_does_not_carry_an_explained_comment_past_a_blank_line(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: auto\n# Pick the worker count.\n\ncache = true\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {}

    def it_attributes_a_default_comment_separated_from_its_key_by_one_blank_line(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text('```toml\n[tool.pytest-gremlins]\n# Default: 10\n\nbatch_size = 10\n```\n', encoding='utf-8')

        assert toml_default_comments(page) == {'batch_size': '10'}

    def it_does_not_carry_a_comment_past_a_commented_out_table_header(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: auto\n# [tool.other]\ncache = true\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {}

    def it_keeps_a_default_comment_across_prose_that_looks_like_an_assignment(self, tmp_path: Path) -> None:
        page = tmp_path / 'configuration.md'
        page.write_text(
            '```toml\n[tool.pytest-gremlins]\n# Default: not set\n# auto = os.cpu_count()\nworkers = "auto"\n```\n',
            encoding='utf-8',
        )

        assert toml_default_comments(page) == {'workers': 'not set'}

    def it_attributes_every_default_comment_on_the_real_configuration_page(self):
        default_comment_count = sum(
            line.lstrip().startswith('# Default:')
            for line in CONFIGURATION_PAGE.read_text(encoding='utf-8').splitlines()
        )

        assert len(toml_default_comments(CONFIGURATION_PAGE)) == default_comment_count
