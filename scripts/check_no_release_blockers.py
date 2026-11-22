#!/usr/bin/env python3
"""Release blocker gate: fail the release while any issue or pull request carries the ``release-blocker`` label.

A maintainer puts the ``release-blocker`` label on an issue that must be fixed before the next release ships. This
gate asks GitHub for every open issue with that label and fails while there is one. The issues endpoint also lists
pull requests, and a labeled pull request counts as a blocker too, so the gate fails closed on it and names it as a
pull request.

The label is looked up first. A deleted or renamed label would otherwise make the listing come back empty and the
gate pass without checking anything, so a missing label is exit 2, never a pass. An empty list only ever comes from
a well-formed 200 answer.

To clear the gate, remove the ``release-blocker`` label from the issue (or close it). That leaves a visible record on
the issue. Nothing skips this check: it has no flag, environment variable or input that turns it off.

Usage: ``check_no_release_blockers.py [--repo OWNER/NAME]``

Reads ``GITHUB_TOKEN`` (needs ``issues: read``) and, unless ``--repo`` is given, ``GITHUB_REPOSITORY``.

Exit codes: 0 when no release blocker is open, 1 when one or more are (each is printed on stdout as ``#N title``,
with how to clear it), 2 when the check could not run (no token, API errors, malformed answers, bad input; the reason
is printed on stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import http.client
import json
import os
import re
import sys
from typing import Any
import urllib.error
import urllib.request

from check_ci_passed import (
    CannotCheckError,
    Fetch,
    github_fetcher,
)

RELEASE_BLOCKER_LABEL = 'release-blocker'
PER_PAGE = 100
HTTP_NOT_FOUND = 404
REPO_PATTERN = re.compile(r'[^/\s]+/[^/\s]+')


@dataclass(frozen=True)
class Blocker:
    """One open item that carries the release-blocker label."""

    number: int
    title: str
    is_pull_request: bool


def _unexpected_shape_error(what: str, answer: object) -> CannotCheckError:
    return CannotCheckError(f'GitHub API answered with an unexpected shape for {what}: {answer!r:.200}')


def _require_label_exists(fetch: Fetch, repo: str) -> None:
    """Raise unless the release-blocker label exists, so an empty listing cannot mean a deleted label.

    Raises:
        CannotCheckError: If the label is missing (404) or the lookup answers with anything but an object.
    """
    try:
        label = fetch(f'/repos/{repo}/labels/{RELEASE_BLOCKER_LABEL}')
    except urllib.error.HTTPError as error:
        if error.code == HTTP_NOT_FOUND:
            raise CannotCheckError(
                f'The {RELEASE_BLOCKER_LABEL!r} label does not exist in {repo}. It may have been deleted or '
                f'renamed, which would make the gate pass without checking anything. Recreate it.'
            ) from error
        raise
    if not isinstance(label, dict):
        raise _unexpected_shape_error('the label', label)


def _blocker_from(entry: object) -> Blocker:
    """Return the blocker an issue-listing entry describes, or raise if the entry is malformed."""
    number = entry.get('number') if isinstance(entry, dict) else None
    title = entry.get('title') if isinstance(entry, dict) else None
    if not isinstance(number, int) or isinstance(number, bool) or not isinstance(title, str):
        raise _unexpected_shape_error('an issue entry', entry)
    assert isinstance(entry, dict)  # noqa: S101 - narrowed by the checks above
    return Blocker(number=number, title=title, is_pull_request='pull_request' in entry)


def find_blockers(fetch: Fetch, repo: str) -> list[Blocker]:
    """Return every open issue and pull request that carries the release-blocker label.

    Args:
        fetch: GETs a GitHub API path and returns the parsed JSON.
        repo: The repository as ``OWNER/NAME``.

    Returns:
        The open blockers; empty only when GitHub answered with a well-formed, empty listing.

    Raises:
        CannotCheckError: If the label is missing or an answer has an unexpected shape.
    """
    _require_label_exists(fetch, repo)
    blockers: list[Blocker] = []
    page = 1
    while True:
        path = f'/repos/{repo}/issues?state=open&labels={RELEASE_BLOCKER_LABEL}&per_page={PER_PAGE}'
        answer: Any = fetch(path if page == 1 else f'{path}&page={page}')
        if not isinstance(answer, list):
            raise _unexpected_shape_error('the issue listing', answer)
        blockers.extend(_blocker_from(entry) for entry in answer)
        if len(answer) < PER_PAGE:
            return blockers
        page += 1


def _describe(blocker: Blocker) -> str:
    suffix = ' (pull request)' if blocker.is_pull_request else ''
    return f'#{blocker.number} {blocker.title}{suffix}'


def _failure_message(repo: str, blockers: list[Blocker]) -> str:
    lines = [f'{len(blockers)} open {RELEASE_BLOCKER_LABEL} item(s) in {repo}:']
    lines.extend(f'  {_describe(blocker)}' for blocker in blockers)
    lines.append(
        f'To clear it, fix the problem, or if it should not block the release, remove the {RELEASE_BLOCKER_LABEL} '
        'label from the issue. The label change stays visible on the issue.'
    )
    return '\n'.join(lines)


def _report_failure(message: str) -> None:
    """Print the failure, plus a GitHub Actions error annotation when running in Actions."""
    print(message)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        escaped = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Release blocker gate failed::{escaped}')


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line; ``None`` reads ``sys.argv``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo', default=os.environ.get('GITHUB_REPOSITORY'), help='OWNER/NAME (default: $GITHUB_REPOSITORY)'
    )
    return parser.parse_args(argv)


def _require_inputs(args: argparse.Namespace) -> str:
    """Validate the arguments and environment, returning the API token."""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise CannotCheckError('GITHUB_TOKEN is required')
    if not args.repo or REPO_PATTERN.fullmatch(args.repo) is None:
        raise CannotCheckError(
            f'a repository as OWNER/NAME (--repo or GITHUB_REPOSITORY) is required, got {args.repo!r}'
        )
    return token


def main(argv: Sequence[str] | None = None) -> int:
    """Run the gate for the repository given on the command line or in the environment.

    Args:
        argv: The command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        The process exit code: 0 when no blocker is open, 1 when one is, 2 when the check could not run.
    """
    args = _parse_args(argv)
    try:
        token = _require_inputs(args)
        blockers = find_blockers(github_fetcher(token), args.repo)
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        print(f'error: GitHub API request failed: {error!r}', file=sys.stderr)
        return 2
    if blockers:
        _report_failure(_failure_message(args.repo, blockers))
        return 1
    print(f'No open {RELEASE_BLOCKER_LABEL} issues in {args.repo}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
