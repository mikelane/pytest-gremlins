#!/usr/bin/env python3
"""Release wip gate: refuse a release whose tagged commit contains a ``wip`` test.

``wip`` marks scenarios for a feature that is not finished. Pull requests may carry them (CI deselects them), but a
release must not ship an unfinished feature. The check has two parts, and runs nothing, so it takes seconds:

* it collects with ``pytest -m wip --collect-only -q``, which catches any test carrying a ``wip`` marker.
* it reads ``features/**/*.feature`` directly for a ``@wip`` tag on a Feature, Rule, Scenario or Examples. This
  direct scan is what catches ``@wip`` scenarios; it does not rely on pytest collecting them, so it needs no
  pytest-bdd. Only tag lines count: a comment, a longer tag such as ``@wipe``, and ``@wip`` inside step or
  description text do not.

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
TAGGABLE_ELEMENT = re.compile(
    r'(Feature|Business Need|Ability|Rule|Scenario Outline|Scenario Template|Scenario|Examples|Scenarios|Example)\s*:'
)
# Headers whose body holds steps. Under Feature, Rule, Examples and Scenarios the same words are description text.
STEP_CONTAINER = re.compile(r'(Background|Scenario Outline|Scenario Template|Scenario|Example)\s*:')
DOCSTRING_FENCES = ('"""', '```')
# A doc string can only open directly after a step line inside a step container; elsewhere a fence is description text.
STEP_LINE = re.compile(r'(Given|When|Then|And|But|\*)(\s|$)')
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


def _tag_tokens(line: str) -> list[str] | None:
    """Return the tags on a tag line, or None when the line is not made only of ``@tag`` tokens."""
    tokens = TRAILING_COMMENT.sub('', line.strip()).split()
    return tokens if tokens and all(token.startswith('@') and len(token) > 1 for token in tokens) else None


def _in_step_container(stripped: str, in_steps: bool) -> bool:
    """Return whether the line after ``stripped`` is inside a step container (Background, Scenario, Example)."""
    if STEP_CONTAINER.match(stripped):
        return True
    if TAGGABLE_ELEMENT.match(stripped):
        return False
    return in_steps


def _wip_tag_lines_in(text: str) -> list[int]:
    """Return the 1-based numbers of the ``@wip`` tag lines in feature text that attach to a Gherkin element."""
    hits: list[int] = []
    pending: list[int] = []
    open_fence: str | None = None
    after_step = False
    in_steps = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        fence = next((fence for fence in DOCSTRING_FENCES if stripped.startswith(fence)), None)
        if open_fence is None and fence is not None and after_step:
            open_fence = fence
            continue
        if open_fence is not None:
            if fence == open_fence:
                open_fence = None
            continue
        if not stripped or stripped.startswith('#'):
            continue
        in_steps = _in_step_container(stripped, in_steps)
        after_step = in_steps and STEP_LINE.match(stripped) is not None
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
    """Return ``file:line`` for every ``@wip`` tag in ``features/**/*.feature``, without importing pytest-bdd.

    Args:
        repo: The repository root holding the ``features`` directory.

    Returns:
        A POSIX ``relative/path.feature:line`` entry per ``@wip`` tag line, sorted by file.

    Raises:
        CannotCheckError: If a feature file cannot be read or is not valid UTF-8.
    """
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
    """Print the wip findings, plus a GitHub Actions error annotation when running in Actions."""
    listing = '\n'.join(f'  {test_id}' for test_id in wip_tests)
    message = f'{len(wip_tests)} wip test(s) or tag(s) found; a release must not ship an unfinished feature:\n{listing}'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        escaped = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Release contains wip tests::{escaped}')
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
