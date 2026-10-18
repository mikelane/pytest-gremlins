"""Facts read from the docs pages and from the plugin, shared by the docs drift tests.

The option list comes from the plugin's real ``pytest_addoption`` hook, so it cannot drift from the code
the docs describe.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from pytest_gremlins.config import load_config
from pytest_gremlins.plugin import pytest_addoption

from .emitted_messages import MESSAGE_PREFIX

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / 'docs'
CONFIGURATION_PAGE = DOCS_ROOT / 'guide' / 'configuration.md'

# Options registered with help=argparse.SUPPRESS are exempt from the documentation check. Listing them here keeps
# every exemption visible; a hidden option that is not listed fails the suite.
HIDDEN_OPTIONS: frozenset[str] = frozenset()

USAGE_ERROR_PREFIX = 'ERROR: '

FLAG_MENTION = re.compile(r'(?<![\w-])(--(?:gremlins?|strict-pardons|max-pardons)(?:-[a-z0-9]+)*)(?![\w*-])')
DEFAULT_COLUMN_HEADER = 'Default'

_HELP_DEFAULT = re.compile(r'\(default: ([^,)]+)')
_TABLE_ROW_FLAG = re.compile(r'^\|\s*`(--[a-z0-9-]+)`\s*\|')
_FENCE = re.compile(r'^\s*```(\w*)')


class DocsFormatError(ValueError):
    """A docs page is shaped in a way the drift checks cannot read; the message names the page and line."""


@dataclass(frozen=True)
class RegisteredOption:
    """One command-line option as the plugin's parser registers it."""

    flag: str
    default: object
    hidden: bool


class _RecordedOption:
    """One ``addoption`` call: its flag names and keyword arguments, as the plugin passed them."""

    def __init__(self, names: tuple[str, ...], attrs: dict[str, Any]) -> None:
        self._names = names
        self._attrs = attrs

    def names(self) -> list[str]:
        return list(self._names)

    def attrs(self) -> dict[str, Any]:
        return self._attrs

    @property
    def default(self) -> object:
        if 'default' in self._attrs:
            return self._attrs['default']
        return {'store_true': False, 'store_false': True}.get(self._attrs.get('action'))


class _RecordingGroup:
    """Stands in for a pytest option group and records every option added to it."""

    def __init__(self, recorded: list[_RecordedOption]) -> None:
        self._recorded = recorded

    def addoption(self, *names: str, **attrs: Any) -> None:
        self._recorded.append(_RecordedOption(names, attrs))


class _RecordingParser(_RecordingGroup):
    """Stands in for ``pytest.Parser`` using only the public ``addoption`` / ``getgroup`` surface.

    Pytest's own ``Parser`` and ``Argument`` internals differ between releases, so the hook is run against
    this recorder instead of a real parser.
    """

    def getgroup(self, *_group_args: object, **_group_kwargs: object) -> _RecordingGroup:
        return _RecordingGroup(self._recorded)


def _registered_parser_options() -> list[Any]:
    """Return every option the plugin's hook registers, whichever group (or none) it adds them to."""
    recorded: list[_RecordedOption] = []
    pytest_addoption(_RecordingParser(recorded))  # type: ignore[arg-type]
    return recorded


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


def fenced_blocks(page: Path) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return ``(language, [(line_number, line), ...])`` for every fenced code block on ``page``."""
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    language: str | None = None
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence and language is None:
            language, lines = fence.group(1), []
        elif fence and language is not None:
            blocks.append((language, lines))
            language = None
        elif language is not None:
            lines.append((number, line))
    return blocks


def _location(page: Path, line_number: int) -> str:
    return f'{page.name}:{line_number}'


def pytest_gremlins_toml_blocks(page: Path = CONFIGURATION_PAGE) -> list[dict[str, object]]:
    """Return the ``[tool.pytest-gremlins]`` table of every TOML block on ``page`` that has one."""
    tables: list[dict[str, object]] = []
    for language, lines in fenced_blocks(page):
        if language != 'toml':
            continue
        try:
            parsed = tomllib.loads('\n'.join(text for _, text in lines))
        except tomllib.TOMLDecodeError as error:
            fence_line = lines[0][0] - 1 if lines else 0
            msg = f'{_location(page, fence_line)}: this TOML block does not parse ({error})'
            raise DocsFormatError(msg) from error
        table = parsed.get('tool', {}).get('pytest-gremlins')
        if table is not None:
            tables.append(table)
    return tables


def _cells(line: str) -> list[str]:
    return [column.strip() for column in line.strip().strip('|').split('|')]


def default_cells(page: Path = CONFIGURATION_PAGE) -> dict[str, str]:
    """Map each name in the first column of a ``Default`` table on ``page`` to its raw Default cell.

    The Default column is the one whose header is ``Default``, wherever it sits.
    """
    cells: dict[str, str] = {}
    default_column: int | None = None
    for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), start=1):
        columns = _cells(line)
        if not line.lstrip().startswith('|'):
            default_column = None
        elif DEFAULT_COLUMN_HEADER in columns:
            default_column = columns.index(DEFAULT_COLUMN_HEADER)
        elif default_column is not None and columns[0].startswith('`'):
            if default_column >= len(columns):
                msg = f'{_location(page, number)}: row has no {DEFAULT_COLUMN_HEADER} cell: {line.strip()}'
                raise DocsFormatError(msg)
            cells[columns[0].strip('`')] = columns[default_column]
    return cells


def documented_keys(page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Return the ``pyproject.toml`` keys named in a ``Default`` table on ``page`` (everything but flags)."""
    return frozenset(name for name in default_cells(page) if not name.startswith('--'))


def keys_shown_in_toml_blocks(page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Return the keys that appear under ``[tool.pytest-gremlins]`` in any TOML block on ``page``."""
    return frozenset(key for block in pytest_gremlins_toml_blocks(page) for key in block)


def keys_the_loader_ignores(workdir: Path, page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Load each TOML example value on ``page`` from ``workdir`` and return the keys that did not reach the config."""
    ignored: set[str] = set()
    for block in pytest_gremlins_toml_blocks(page):
        for key, value in block.items():
            (workdir / 'pyproject.toml').write_text(
                f'[tool.pytest-gremlins]\n{key} = {_toml_literal(value)}\n', encoding='utf-8'
            )
            if getattr(load_config(workdir), key.replace('-', '_'), None) is None:
                ignored.add(key)
    return frozenset(ignored)


def _toml_literal(value: object) -> str:
    return 'true' if value is True else 'false' if value is False else json.dumps(value)


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
            for index, (number, line) in enumerate(lines):
                text = line.strip().removeprefix(USAGE_ERROR_PREFIX)
                if text.startswith(MESSAGE_PREFIX):
                    following = lines[index + 1][1].strip() if index + 1 < len(lines) else ''
                    quoted.append(
                        QuotedMessage(
                            page=page,
                            line_number=number,
                            text=text,
                            continues=bool(following) and not following.startswith(MESSAGE_PREFIX),
                        )
                    )
    return quoted
