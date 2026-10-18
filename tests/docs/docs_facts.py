"""Facts read from the docs pages and from the plugin, shared by the docs drift tests.

The option list comes from the plugin's real ``pytest_addoption`` hook, so it cannot drift from the code
the docs describe.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Any

import pytest

from pytest_gremlins.plugin import pytest_addoption

from .emitted_messages import MESSAGE_PREFIX

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / 'docs'
CONFIGURATION_PAGE = DOCS_ROOT / 'guide' / 'configuration.md'

# Options registered with help=argparse.SUPPRESS are exempt from the documentation check. Listing them here keeps
# every exemption visible; a hidden option that is not listed fails the suite.
HIDDEN_OPTIONS: frozenset[str] = frozenset()

FLAG_MENTION = re.compile(r'(?<![\w-])(--(?:gremlins?|strict-pardons|max-pardons)(?:-[a-z0-9]+)*)(?![\w*-])')
_HELP_DEFAULT = re.compile(r'\(default: ([^,)]+)')
_TABLE_ROW_FLAG = re.compile(r'^\|\s*`(--[a-z0-9-]+)`\s*\|')


@dataclass(frozen=True)
class RegisteredOption:
    """One command-line option as the plugin's parser registers it."""

    flag: str
    default: object
    hidden: bool


def _registered_parser_options() -> list[Any]:
    """Return the option objects of every group after the plugin's hook has run on a fresh parser.

    A fresh parser holds no pytest built-ins, so every option found here is the plugin's own, whether the hook
    put it in the ``gremlins`` group, another named group or the anonymous group (``parser.addoption``).
    """
    parser = pytest.Parser(_ispytest=True)
    pytest_addoption(parser)
    return [option for group in parser._groups for option in group.options]


def registered_options() -> list[RegisteredOption]:
    """Return every option the plugin registers, read from the real parser."""
    return [
        RegisteredOption(
            flag=flag,
            default=option.default,
            hidden=option.attrs().get('help') == argparse.SUPPRESS,
        )
        for option in _registered_parser_options()
        for flag in option.names()
    ]


def registered_help_defaults() -> dict[str, str]:
    """Map each flag whose help text states ``(default: X...)`` to that ``X``."""
    stated: dict[str, str] = {}
    for option in _registered_parser_options():
        match = _HELP_DEFAULT.search(option.attrs().get('help') or '')
        if match:
            stated.update(dict.fromkeys(option.names(), match.group(1)))
    return stated


def registered_flags() -> frozenset[str]:
    """Return the flag names of every option the plugin registers."""
    return frozenset(option.flag for option in registered_options())


def hidden_flags() -> frozenset[str]:
    """Return the flags the parser registers with ``help=argparse.SUPPRESS``."""
    return frozenset(option.flag for option in registered_options() if option.hidden)


def documented_flags(page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Return the flags that start a row of an options table on ``page``."""
    rows = (_TABLE_ROW_FLAG.match(line) for line in page.read_text(encoding='utf-8').splitlines())
    return frozenset(row.group(1) for row in rows if row)


def flags_mentioned_in_docs(docs_root: Path = DOCS_ROOT) -> dict[str, list[str]]:
    """Map each pytest-gremlins flag mentioned under ``docs_root`` to the pages that mention it."""
    mentions: dict[str, set[str]] = {}
    for page in sorted(docs_root.rglob('*.md')):
        for flag in FLAG_MENTION.findall(page.read_text(encoding='utf-8')):
            mentions.setdefault(flag, set()).add(str(page.relative_to(docs_root)))
    return {flag: sorted(pages) for flag, pages in mentions.items()}


_FENCE = re.compile(r'^\s*```(\w*)')
CONFIG_TABLE = 'tool.pytest-gremlins'


def fenced_blocks(page: Path) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return ``(language, [(line_number, line), ...])`` for every fenced code block on ``page``."""
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    language: str | None = None
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence and language is None:
            language, lines = fence.group(1), []
        elif fence:
            blocks.append((language, lines))
            language = None
        elif language is not None:
            lines.append((number, line))
    return blocks


def pytest_gremlins_toml_blocks(page: Path = CONFIGURATION_PAGE) -> list[dict[str, object]]:
    """Return the ``[tool.pytest-gremlins]`` table of every TOML block on ``page`` that has one."""
    tables: list[dict[str, object]] = []
    for language, lines in fenced_blocks(page):
        if language != 'toml':
            continue
        parsed = tomllib.loads('\n'.join(text for _, text in lines))
        table = parsed.get('tool', {}).get('pytest-gremlins')
        if table is not None:
            tables.append(table)
    return tables


def default_cells(page: Path = CONFIGURATION_PAGE) -> dict[str, str]:
    """Map each name in the first column of a ``Default`` table on ``page`` to its raw Default cell."""
    cells: dict[str, str] = {}
    in_default_table = False
    for line in page.read_text(encoding='utf-8').splitlines():
        columns = [column.strip() for column in line.strip().strip('|').split('|')]
        if not line.lstrip().startswith('|'):
            in_default_table = False
        elif 'Default' in columns:
            in_default_table = columns.index('Default') == _DEFAULT_COLUMN
        elif in_default_table and columns[0].startswith('`'):
            cells[columns[0].strip('`')] = columns[_DEFAULT_COLUMN]
    return cells


_DEFAULT_COLUMN = 2


@dataclass(frozen=True)
class QuotedMessage:
    """A line that starts with ``pytest-gremlins:`` inside a fenced code block of a docs page."""

    page: Path
    line_number: int
    text: str
    continues: bool

    @property
    def location(self) -> str:
        """Return ``docs/relative/path.md:LINE``."""
        return f'docs/{self.page.relative_to(DOCS_ROOT)}:{self.line_number}'


def quoted_messages(docs_root: Path = DOCS_ROOT) -> list[QuotedMessage]:
    """Return every ``pytest-gremlins:`` line quoted inside a fenced code block under ``docs_root``.

    ``continues`` is true when the next line of the block carries on the message, as in a wrapped warning.
    """
    quoted: list[QuotedMessage] = []
    for page in sorted(docs_root.rglob('*.md')):
        for _, lines in fenced_blocks(page):
            for index, (number, text) in enumerate(lines):
                if text.strip().startswith(MESSAGE_PREFIX):
                    following = lines[index + 1][1].strip() if index + 1 < len(lines) else ''
                    quoted.append(
                        QuotedMessage(
                            page=page,
                            line_number=number,
                            text=text.strip(),
                            continues=bool(following) and not following.startswith(MESSAGE_PREFIX),
                        )
                    )
    return quoted
