"""Facts read from the docs pages and from the plugin, shared by the docs drift tests.

The option list comes from the plugin's real ``pytest_addoption`` hook, so it cannot drift from the code
the docs describe.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from pytest_gremlins.config import (
    CONFIG_KEYS,
    load_config,
)
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
_DEFAULT_COMMENT = re.compile(r'^#\s*Default:\s*(.+)$')
_TOML_ASSIGNMENT = re.compile(r'^([A-Za-z0-9_-]+)\s*=')
_FENCE = re.compile(r'^\s*(`{3,}|~{3,})\s*(\w*)')
_MULTI_LINE_VALUE_OPENERS = ('[', '{', '"""', "'''")


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
        return {'store_true': False, 'store_false': True}.get(self._attrs.get('action', ''))


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
    """Return the flags that start a row of a ``Default`` table on ``page``.

    A flag listed only in a table without a ``Default`` column does not count, so every documented flag has a
    default the drift checks compare with the code.
    """
    return frozenset(name for name in default_cells(page) if name.startswith('--'))


def flags_mentioned_in_docs(docs_root: Path = DOCS_ROOT) -> dict[str, list[str]]:
    """Map each pytest-gremlins flag mentioned under ``docs_root`` to the pages that mention it."""
    mentions: dict[str, set[str]] = {}
    for page in sorted(docs_root.rglob('*.md')):
        for flag in FLAG_MENTION.findall(page.read_text(encoding='utf-8')):
            mentions.setdefault(flag, set()).add(str(page.relative_to(docs_root)))
    return {flag: sorted(pages) for flag, pages in mentions.items()}


def fenced_blocks(page: Path) -> list[tuple[str, list[tuple[int, str]]]]:
    """Return ``(language, [(line_number, line), ...])`` for every fenced code block on ``page``.

    A block opened with backticks closes only at backticks, and one opened with tildes only at tildes. The
    language tag is lowercased.
    """
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    opening_marker: str | None = None
    language = ''
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence and opening_marker is None:
            opening_marker, language, lines = fence.group(1), fence.group(2).lower(), []
        elif fence and _closes(opening_marker, fence.group(1), fence.group(2)):
            blocks.append((language, lines))
            opening_marker = None
        elif opening_marker is not None:
            lines.append((number, line))
    return blocks


def _closes(opening_marker: str | None, marker: str, trailing_text: str) -> bool:
    """Return whether a fence line closes a block: same character, at least as long, and no info string."""
    return (
        opening_marker is not None
        and not trailing_text
        and marker[0] == opening_marker[0]
        and len(marker) >= len(opening_marker)
    )


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

    The Default column is the one whose header is ``Default``, wherever it sits. A name may have only one row.
    """
    cells: dict[str, str] = {}
    line_by_name: dict[str, int] = {}
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
            name = columns[0].strip('`')
            if name in line_by_name:
                first_row = line_by_name[name]
                msg = f'{_location(page, number)}: {name} already has a {DEFAULT_COLUMN_HEADER} row at line {first_row}'
                raise DocsFormatError(msg)
            line_by_name[name] = number
            cells[name] = columns[default_column]
    return cells


def documented_keys(page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Return the ``pyproject.toml`` keys named in a ``Default`` table on ``page`` (everything but flags)."""
    return frozenset(name for name in default_cells(page) if not name.startswith('--'))


def keys_shown_in_toml_blocks(page: Path = CONFIGURATION_PAGE) -> frozenset[str]:
    """Return the keys that appear under ``[tool.pytest-gremlins]`` in any TOML block on ``page``."""
    return frozenset(key for block in pytest_gremlins_toml_blocks(page) for key in block)


def toml_keys_the_loader_does_not_read(keys: Iterable[str]) -> frozenset[str]:
    """Return the ``keys`` the loader does not read, accepting the hyphen or underscore spelling it accepts."""
    read = {key.replace('-', '_') for key in CONFIG_KEYS}
    return frozenset(key for key in keys if key.replace('-', '_') not in read)


def pages_showing_toml_keys_outside_configuration_page(docs_root: Path = DOCS_ROOT) -> dict[str, list[str]]:
    """Map each ``[tool.pytest-gremlins]`` key in a TOML block on any other page under ``docs_root`` to its pages."""
    pages_by_key: dict[str, set[str]] = {}
    for page in sorted(docs_root.rglob('*.md')):
        if page == CONFIGURATION_PAGE:
            continue
        for key in keys_shown_in_toml_blocks(page):
            pages_by_key.setdefault(key, set()).add(str(page.relative_to(docs_root)))
    return {key: sorted(pages) for key, pages in pages_by_key.items()}


def toml_default_comments(page: Path = CONFIGURATION_PAGE) -> dict[str, str]:
    """Map each key in a TOML block on ``page`` to the text of the ``# Default:`` comment above it."""
    comments: dict[str, str] = {}
    for language, lines in fenced_blocks(page):
        if language != 'toml':
            continue
        pending = _PendingDefault()
        for _, line in lines:
            text = line.strip()
            comment = _DEFAULT_COMMENT.match(text)
            assignment = _TOML_ASSIGNMENT.match(text)
            if comment:
                pending = _PendingDefault(comment.group(1))
            elif assignment and pending.stated is not None:
                comments[assignment.group(1)] = pending.stated
                pending = _PendingDefault()
            else:
                pending = pending.after(text)
    return comments


@dataclass(frozen=True)
class _PendingDefault:
    """A ``# Default:`` comment waiting for the assignment it describes.

    Explanatory comment lines may follow it, and a blank line may sit right above the assignment. A blank line
    between the Default and any other comment line ends the wait: the Default belonged to a deleted key, and the
    comment starts the next key's paragraph.
    """

    stated: str | None = None
    explained: bool = False
    blank_seen: bool = False

    def after(self, text: str) -> _PendingDefault:
        """Return the pending Default after a line that is neither a Default comment nor an assignment."""
        if self.stated is None or self._ends_at(text):
            return _PendingDefault()
        if text:
            return _PendingDefault(self.stated, explained=True, blank_seen=self.blank_seen)
        return _PendingDefault(self.stated, explained=self.explained, blank_seen=True)

    def _ends_at(self, text: str) -> bool:
        if not text:
            return self.explained
        if not text.startswith('#'):
            return True
        body = text.lstrip('#').strip()
        return self.blank_seen or body.startswith('[') or _is_commented_out_setting(body)


def _is_commented_out_setting(text: str) -> bool:
    """Return whether ``text`` is a TOML assignment, not prose that happens to start with ``word =``."""
    assignment = _TOML_ASSIGNMENT.match(text)
    if not assignment:
        return False
    if text[assignment.end() :].lstrip().startswith(_MULTI_LINE_VALUE_OPENERS):
        return True
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    return True


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
