"""Facts read from the docs pages and from the plugin, shared by the docs drift tests.

The option list comes from the plugin's real ``pytest_addoption`` hook, so it cannot drift from the code
the docs describe.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

import pytest

from pytest_gremlins.plugin import pytest_addoption

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / 'docs'
CONFIGURATION_PAGE = DOCS_ROOT / 'guide' / 'configuration.md'

GROUP_NAME = 'gremlins'

# Options registered with help=argparse.SUPPRESS are exempt from the documentation check. Listing them here keeps
# every exemption visible; a hidden option that is not listed fails the suite.
HIDDEN_OPTIONS: frozenset[str] = frozenset()

FLAG_MENTION = re.compile(r'(?<![\w-])(--(?:gremlins?|strict-pardons|max-pardons)(?:-[a-z0-9]+)*)(?![\w*-])')
_TABLE_ROW_FLAG = re.compile(r'^\|\s*`(--[a-z0-9-]+)`\s*\|')


@dataclass(frozen=True)
class RegisteredOption:
    """One command-line option as the plugin's parser registers it."""

    flag: str
    default: object
    hidden: bool


def registered_options() -> list[RegisteredOption]:
    """Return every option the plugin registers, read from the real parser."""
    parser = pytest.Parser(_ispytest=True)
    pytest_addoption(parser)
    return [
        RegisteredOption(
            flag=flag,
            default=option.default,
            hidden=option.attrs().get('help') == argparse.SUPPRESS,
        )
        for option in parser.getgroup(GROUP_NAME).options
        for flag in option.names()
    ]


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
