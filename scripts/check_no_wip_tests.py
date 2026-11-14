#!/usr/bin/env python3
"""Release wip gate: refuse a release whose tagged commit contains a ``wip`` test.

``wip`` marks scenarios for a feature that is not finished. Pull requests may carry them (CI deselects them), but a
release must not ship an unfinished feature. The check has two parts, and runs nothing, so it takes seconds:

* it collects with ``pytest -m wip --collect-only -q``. pytest-bdd turns a Gherkin ``@wip`` tag into the ``wip``
  marker, so scenarios wired to pytest-bdd are collected too.
* it reads ``features/**/*.feature`` directly for a ``@wip`` tag on a Feature, Rule, Scenario or Examples, so
  scenarios that nothing collects yet are caught without pytest-bdd. Only tag lines count: a comment, a longer tag such
  as ``@wipe``, and ``@wip`` inside step or description text do not.

Nothing skips this check: it has no flag, environment variable or input that turns it off. An urgent fix that cannot
wait for an unfinished feature is released from a branch off the previous release tag, not from main.

Usage: ``check_no_wip_tests.py [--repo PATH]``

Exit codes: 0 when no ``wip`` test or tag exists, 1 when one does (each test ID, or ``file:line`` of each tag, is
printed on stdout), 2 when the check could not run (collection failed or a feature file is unreadable; the reason is
printed on stderr). Exit 2 is never a pass. A ``@wip`` tag still exits 1 when collection also fails.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

PYTEST_NO_TESTS_COLLECTED = 5
FEATURES_DIRECTORY = 'features'
WIP_TAG = '@wip'
# A tag line holds only ``@tag`` tokens, optionally followed by a ``# comment``.
TRAILING_COMMENT = re.compile(r'\s+#.*$')
# Tags attach to the Gherkin element on the next line that is not a blank, a comment or another tag line.
TAGGABLE_ELEMENT = re.compile(r'(Feature|Rule|Scenario Outline|Scenario Template|Scenario|Examples?)\s*:')
DOCSTRING_FENCES = ('"""', '```')
# A node ID is one whitespace-free token holding ``::``; a warning that merely quotes an ID has a space before it.
TEST_ID_LINE = re.compile(r'\S+::')


class CannotCheckError(Exception):
    """Raised when collection fails, so the repository cannot be checked."""


def parse_collected_ids(output: str) -> list[str]:
    """Return the test IDs from ``--collect-only -q`` output, dropping the summary line."""
    return [line for line in output.splitlines() if TEST_ID_LINE.match(line)]


def find_wip_tests(repo: Path) -> list[str]:
    """Return the ID of every ``wip`` test collected in ``repo``."""
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-m', 'wip', '--collect-only', '-q', '-p', 'no:cacheprovider'],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == PYTEST_NO_TESTS_COLLECTED:
        return []
    if result.returncode != 0:
        raise CannotCheckError(
            f'pytest exited {result.returncode} while collecting wip tests:\n{result.stdout}\n{result.stderr}'
        )
    return parse_collected_ids(result.stdout)


def _tag_tokens(line: str) -> list[str] | None:
    """Return the tags on a tag line, or None when the line is not made only of ``@tag`` tokens."""
    tokens = TRAILING_COMMENT.sub('', line.strip()).split()
    return tokens if tokens and all(token.startswith('@') and len(token) > 1 for token in tokens) else None


def _wip_tag_lines_in(text: str) -> list[int]:
    """Return the 1-based numbers of the ``@wip`` tag lines in feature text that attach to a Gherkin element."""
    hits: list[int] = []
    pending: list[int] = []
    in_docstring = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(DOCSTRING_FENCES):
            in_docstring = not in_docstring
        if in_docstring or not stripped or stripped.startswith('#'):
            continue
        tokens = _tag_tokens(line)
        if tokens is not None:
            if WIP_TAG in tokens:
                pending.append(number)
            continue
        if TAGGABLE_ELEMENT.match(stripped):
            hits.extend(pending)
        pending = []
    return hits


def find_wip_feature_tags(repo: Path) -> list[str]:
    """Return ``file:line`` for every ``@wip`` tag in ``features/**/*.feature``, without importing pytest-bdd."""
    found: list[str] = []
    for path in sorted((repo / FEATURES_DIRECTORY).rglob('*.feature')):
        relative = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheckError(f'cannot read {relative}: {error}') from error
        found.extend(f'{relative}:{number}' for number in _wip_tag_lines_in(text))
    return found


def _report_failure(wip_tests: list[str]) -> None:
    listing = '\n'.join(f'  {test_id}' for test_id in wip_tests)
    message = f'{len(wip_tests)} wip test(s) or tag(s) found; a release must not ship an unfinished feature:\n{listing}'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::error title=Release contains wip tests::{message.replace(chr(10), "%0A")}')
    print(message)


def main() -> int:
    """Check the repository given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        tagged = find_wip_feature_tags(args.repo)
        try:
            collected = find_wip_tests(args.repo)
        except CannotCheckError:
            if not tagged:
                raise
            collected = []
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    wip_tests = [*collected, *tagged]
    if wip_tests:
        _report_failure(wip_tests)
        return 1
    print('No wip tests found')
    return 0


if __name__ == '__main__':
    sys.exit(main())
