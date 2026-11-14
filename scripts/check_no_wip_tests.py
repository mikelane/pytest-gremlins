#!/usr/bin/env python3
"""Release wip gate: refuse a release whose tagged commit contains a ``wip`` test.

``wip`` marks scenarios for a feature that is not finished. Pull requests may carry them (CI deselects them), but a
release must not ship an unfinished feature. The check has two parts, and runs nothing, so it takes seconds:

* it collects with ``pytest -m wip --collect-only -q``, which catches any test carrying a ``wip`` marker.
* it parses ``features/**/*.feature`` with the official Gherkin parser (``gherkin-official``) for a ``@wip`` tag on
  a Feature, Rule, Scenario, Scenario Outline or Examples. This direct scan is what catches ``@wip`` scenarios; it
  does not rely on pytest collecting them, so it needs no pytest-bdd. Only real tags count: a comment, a longer tag
  such as ``@wipe``, and ``@wip`` inside step, description or doc string text do not. A file the parser rejects
  cannot be checked, so it exits 2.

Nothing skips this check: it has no flag, environment variable or input that turns it off. An urgent fix that cannot
wait for an unfinished feature is released from a branch off the previous release tag, not from main. That path
depends on #1015 (``ci.yml`` must run for that branch); until then ``check_ci_passed.py`` fails such a tag after its
10-minute grace. Re-dispatching ``release.yml`` for a tag cut before this gate existed fails closed: the gate scripts
do not exist at that tag.

Usage: ``check_no_wip_tests.py [--repo PATH]``

Exit codes: 0 when no ``wip`` test or tag exists, 1 when one does (each test ID, or ``file:line`` of each tag, is
printed on stdout), 2 when the check could not run (collection failed or a feature file is unreadable; the reason is
printed on stderr). Exit 2 is never a pass. A ``@wip`` tag still exits 1 when collection also fails.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

PYTEST_NO_TESTS_COLLECTED = 5
FEATURES_DIRECTORY = 'features'
WIP_TAG = '@wip'
# A node ID is one whitespace-free token holding ``::``; a warning that merely quotes an ID has a space before it.
TEST_ID_LINE = re.compile(r'\S+::')


class CannotCheckError(Exception):
    """Raised when collection fails, so the repository cannot be checked."""


def parse_collected_ids(output: str) -> list[str]:
    r"""Return the test IDs from ``--collect-only -q`` output, dropping the summary line.

    Args:
        output: The stdout of ``pytest --collect-only -q``.

    Returns:
        Each line that is a node ID, in collection order.

    Examples:
        >>> parse_collected_ids('tests/test_a.py::test_one\n\n1 test collected in 0.01s\n')
        ['tests/test_a.py::test_one']
    """
    return [line for line in output.splitlines() if TEST_ID_LINE.match(line)]


def find_wip_tests(repo: Path) -> list[str]:
    """Return the ID of every ``wip`` test collected in ``repo``.

    Args:
        repo: The repository root to run ``pytest`` in.

    Returns:
        The node ID of each collected ``wip`` test; empty when pytest collected none.

    Raises:
        CannotCheckError: If pytest exits with any code other than 0 or 5 (no tests collected), or exits 0 but
            its output holds no test IDs (the output format is not the one this parser reads).

    The command line clears ``addopts`` and ``PYTEST_ADDOPTS`` so an extra ``-q`` cannot change the output format.
    """
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'pytest',
            '-m',
            'wip',
            '--collect-only',
            '-q',
            '-p',
            'no:cacheprovider',
            '-o',
            'addopts=',
        ],
        cwd=repo,
        env={name: value for name, value in os.environ.items() if name != 'PYTEST_ADDOPTS'},
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
    collected = parse_collected_ids(result.stdout)
    if not collected:
        raise CannotCheckError(
            f'pytest exited 0 but no test IDs could be read from its output, so the wip check cannot tell what was '
            f'collected:\n{result.stdout}'
        )
    return collected


def _tagged_nodes(node: object) -> Iterator[dict[str, Any]]:
    """Yield every dict in a Gherkin AST that carries a ``tags`` list: Feature, Rule, Scenario and Examples."""
    if isinstance(node, dict):
        if 'tags' in node:
            yield node
        for value in node.values():
            yield from _tagged_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _tagged_nodes(item)


def _wip_tag_lines_in(text: str) -> list[int]:
    """Return the sorted line numbers of the ``@wip`` tags in feature text, as the Gherkin parser reads it.

    Raises:
        CannotCheckError: If the text is not valid Gherkin.
    """
    # Imported here because gherkin reads its language data file on import, and the small tests load this module.
    from gherkin.errors import ParserError  # noqa: PLC0415
    from gherkin.parser import Parser  # noqa: PLC0415

    try:
        document = Parser().parse(text)
    except ParserError as error:
        raise CannotCheckError(str(error)) from error
    return sorted(
        tag['location']['line'] for node in _tagged_nodes(document) for tag in node['tags'] if tag['name'] == WIP_TAG
    )


def find_wip_feature_tags(repo: Path) -> list[str]:
    """Return ``file:line`` for every ``@wip`` tag in ``features/**/*.feature``, without importing pytest-bdd.

    Args:
        repo: The repository root holding the ``features`` directory.

    Returns:
        A POSIX ``relative/path.feature:line`` entry per ``@wip`` tag, sorted by file, then line.

    Raises:
        CannotCheckError: If a feature file cannot be read, is not valid UTF-8, or is not valid Gherkin.
    """
    found: list[str] = []
    for path in sorted((repo / FEATURES_DIRECTORY).rglob('*.feature')):
        relative = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheckError(f'cannot read {relative}: {error}') from error
        try:
            lines = _wip_tag_lines_in(text)
        except CannotCheckError as error:
            raise CannotCheckError(f'cannot parse {relative}: {error}') from error
        found.extend(f'{relative}:{number}' for number in lines)
    return found


def _report_failure(wip_tests: list[str]) -> None:
    """Print the wip findings, plus a GitHub Actions error annotation when running in Actions."""
    listing = '\n'.join(f'  {test_id}' for test_id in wip_tests)
    message = f'{len(wip_tests)} wip test(s) or tag(s) found; a release must not ship an unfinished feature:\n{listing}'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        escaped = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Release contains wip tests::{escaped}')
    print(message)


def main() -> int:
    """Check the repository given on the command line.

    Returns:
        The process exit code: 0 when no wip test or tag exists, 1 when one does, 2 when the check could not run.
    """
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
