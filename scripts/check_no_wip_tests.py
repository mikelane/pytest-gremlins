#!/usr/bin/env python3
"""Release wip gate: refuse a release whose tagged commit contains a ``wip`` test.

``wip`` marks scenarios for a feature that is not finished. Pull requests may carry them (CI deselects them), but a
release must not ship an unfinished feature. The check collects with ``pytest -m wip --collect-only -q`` and runs
nothing, so it takes seconds. pytest-bdd turns a Gherkin ``@wip`` tag into the ``wip`` marker, so tagged scenarios
are collected too.

Nothing skips this check: it has no flag, environment variable or input that turns it off. An urgent fix that cannot
wait for an unfinished feature is released from a branch off the previous release tag, not from main.

Usage: ``check_no_wip_tests.py [--repo PATH]``

Exit codes: 0 when no ``wip`` test exists, 1 when one does (each test ID is printed on stdout), 2 when collection
could not run (the reason is printed on stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

PYTEST_NO_TESTS_COLLECTED = 5
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


def _report_failure(wip_tests: list[str]) -> None:
    listing = '\n'.join(f'  {test_id}' for test_id in wip_tests)
    message = f'{len(wip_tests)} wip test(s) found; a release must not ship an unfinished feature:\n{listing}'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::error title=Release contains wip tests::{message.replace(chr(10), "%0A")}')
    print(message)


def main() -> int:
    """Check the repository given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        wip_tests = find_wip_tests(args.repo)
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    if wip_tests:
        _report_failure(wip_tests)
        return 1
    print('No wip tests found')
    return 0


if __name__ == '__main__':
    sys.exit(main())
