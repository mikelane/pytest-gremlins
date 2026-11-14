#!/usr/bin/env python3
"""Release CI gate: require a passing ``ci.yml`` run, with its test matrix executed, for the tagged commit.

``release.yml`` does not rerun the OS x Python test matrix. Main CI already ran it on the commit the tag points at,
so the release asks GitHub whether that run passed. The run is looked up by commit SHA and the ``push`` event, not by
branch, so a tag on a release branch works as long as CI ran for its commit. It passes when some ``ci.yml`` push run
for the SHA

* completed with conclusion ``success``, and
* has every job in ``EXPECTED_TEST_JOBS`` (the ``Test (Python ..., ...)`` and ``Test (pytest ...)`` matrices) with
  conclusion ``success``. ``ci.yml`` skips those jobs when its change filter sees no source change, and a skipped job
  leaves the run green, so a missing, skipped, failed or cancelled test job fails the gate.

A run that is queued or in progress is waited for until ``--timeout``. If no run exists at all, the gate waits only
``NO_RUN_GRACE_SECONDS`` (10 minutes, for a run CI is about to register) and then fails saying the SHA has no main CI
run, as for a tag on a branch other than main. If no qualifying run exists by the timeout, it fails and names the SHA.
Nothing skips this check: it has no flag, environment variable or input that turns it off.

``EXPECTED_TEST_JOBS`` is pinned to the matrices in ``ci.yml`` by tests/scripts/test_check_ci_passed.py, so changing a
matrix without updating it fails a pull request.

Usage: ``check_ci_passed.py SHA [--repo OWNER/NAME] [--timeout SECONDS] [--interval SECONDS]``

Reads ``GITHUB_TOKEN`` (needs ``actions: read``) and, unless ``--repo`` is given, ``GITHUB_REPOSITORY``.

Exit codes: 0 when CI passed for the SHA, 1 when it did not (the reason is printed on stdout and names the SHA),
2 when the check could not run (no token, API errors, bad input; the reason is printed on stderr). Exit 2 is never a
pass.
"""

from __future__ import annotations

import argparse
from collections.abc import (
    Callable,
    Sequence,
)
from dataclasses import dataclass
import json
import os
import re
import sys
import time
from typing import (
    Any,
    Literal,
)
import urllib.error
import urllib.request

WORKFLOW_FILE = 'ci.yml'
PER_PAGE = 100
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60
DEFAULT_INTERVAL_SECONDS = 60.0
# How long to wait for a ci.yml push run to appear at all. A run that exists (queued or in progress) is waited for
# up to the full timeout; a SHA that never gets one (a tag on a branch other than main) fails after this.
NO_RUN_GRACE_SECONDS = 10 * 60
MAX_CONSECUTIVE_API_ERRORS = 3
REQUEST_TIMEOUT_SECONDS = 30
HTTP_SERVER_ERROR_MIN = 500
HTTP_TOO_MANY_REQUESTS = 429
SHA_PATTERN = re.compile(r'[0-9a-f]{40}')

_PYTHON_VERSIONS = ('3.11', '3.12', '3.13', '3.14')
_OPERATING_SYSTEMS = ('ubuntu-latest', 'macos-latest', 'windows-latest')
_PYTEST_VERSIONS = ('8.4.2', '9.0.0', 'latest')
EXPECTED_TEST_JOBS: tuple[str, ...] = (
    *(f'Test (Python {version}, {os_name})' for os_name in _OPERATING_SYSTEMS for version in _PYTHON_VERSIONS),
    *(f'Test (pytest {version})' for version in _PYTEST_VERSIONS),
)

Fetch = Callable[[str], Any]


class CannotCheckError(Exception):
    """Raised when the GitHub API cannot be queried, so the gate cannot decide."""


@dataclass(frozen=True)
class Outcome:
    """One poll's answer: passed, failed, pending (a run exists) or missing (no run yet), and a reason."""

    state: Literal['passed', 'failed', 'pending', 'missing']
    message: str


def _list_jobs(fetch: Fetch, repo: str, run_id: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = fetch(f'/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page={PER_PAGE}&page={page}')
        batch = list(answer['jobs'])
        jobs.extend(batch)
        if len(batch) < PER_PAGE:
            return jobs
        page += 1


def _test_job_problems(jobs: list[dict[str, Any]]) -> list[str]:
    conclusions = {job['name']: job.get('conclusion') for job in jobs}
    problems = []
    for name in EXPECTED_TEST_JOBS:
        if name not in conclusions:
            problems.append(f'{name}: missing from the run')
        elif conclusions[name] != 'success':
            problems.append(f'{name}: {conclusions[name]}')
    return problems


def _completed_run_problems(fetch: Fetch, repo: str, run: dict[str, Any]) -> list[str]:
    if run.get('conclusion') != 'success':
        return [f'run concluded {run.get("conclusion")}']
    return _test_job_problems(_list_jobs(fetch, repo, int(run['id'])))


def check_ci(fetch: Fetch, repo: str, sha: str) -> Outcome:
    """Evaluate the ``ci.yml`` push runs for ``sha`` once."""
    answer = fetch(
        f'/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?head_sha={sha}&event=push&per_page={PER_PAGE}'
    )
    runs = list(answer['workflow_runs'])
    if not runs:
        return Outcome('missing', f'No {WORKFLOW_FILE} push run found for {sha} yet')
    still_running = False
    failures: list[str] = []
    for run in runs:
        if run.get('status') != 'completed':
            still_running = True
            continue
        problems = _completed_run_problems(fetch, repo, run)
        if not problems:
            return Outcome('passed', f'{WORKFLOW_FILE} passed for {sha} ({run.get("html_url", run["id"])})')
        failures.append(f'{run.get("html_url", run["id"])}: {"; ".join(problems)}')
    if still_running:
        return Outcome('pending', f'{WORKFLOW_FILE} is still running for {sha}')
    return Outcome('failed', f'No passing {WORKFLOW_FILE} run for {sha}:\n  ' + '\n  '.join(failures))


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= HTTP_SERVER_ERROR_MIN or error.code == HTTP_TOO_MANY_REQUESTS
    return True


def wait_for_ci(
    fetch: Fetch,
    repo: str,
    sha: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Outcome:
    """Poll until the gate has an answer, the timeout passes, or the API keeps failing."""
    deadline = monotonic() + timeout_seconds
    absent_since: float | None = None
    consecutive_errors = 0
    while True:
        try:
            outcome = check_ci(fetch, repo, sha)
            consecutive_errors = 0
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as error:
            consecutive_errors += 1
            if not _is_retryable(error) or consecutive_errors >= MAX_CONSECUTIVE_API_ERRORS:
                raise CannotCheckError(f'GitHub API request failed: {error!r}') from error
        else:
            if outcome.state in ('passed', 'failed'):
                return outcome
            print(outcome.message, flush=True)
            now = monotonic()
            absent_since = (now if absent_since is None else absent_since) if outcome.state == 'missing' else None
            if absent_since is not None and now + interval_seconds > absent_since + NO_RUN_GRACE_SECONDS:
                return Outcome(
                    'failed',
                    f'{sha} has no main CI run: no {WORKFLOW_FILE} push run appeared within '
                    f'{NO_RUN_GRACE_SECONDS // 60} minutes. Is the tag on a branch other than main?',
                )
            if now + interval_seconds > deadline:
                return Outcome(
                    'failed', f'Gave up (timed out) waiting for {WORKFLOW_FILE} to pass for {sha}: {outcome.message}'
                )
        sleep(interval_seconds)


def github_fetcher(token: str) -> Fetch:
    """Return a ``fetch(path)`` that GETs ``path`` from the GitHub API and parses the JSON answer."""
    base = os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')
    if not base.startswith('https://'):
        raise CannotCheckError(f'GITHUB_API_URL must be an https URL, got {base!r}')

    def fetch(path: str) -> Any:  # noqa: ANN401 - parsed JSON has no useful static type
        request = urllib.request.Request(  # noqa: S310
            base + path,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.load(response)

    return fetch


def _report_failure(message: str) -> None:
    print(message)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        escaped = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title=Release CI gate failed::{escaped}')


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sha', help='the full commit SHA the release tag points at')
    parser.add_argument(
        '--repo', default=os.environ.get('GITHUB_REPOSITORY'), help='OWNER/NAME (default: $GITHUB_REPOSITORY)'
    )
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT_SECONDS, help='seconds to wait for CI')
    parser.add_argument('--interval', type=float, default=DEFAULT_INTERVAL_SECONDS, help='seconds between polls')
    return parser.parse_args(argv)


def _require_inputs(args: argparse.Namespace) -> str:
    """Validate the arguments and environment, returning the API token."""
    if SHA_PATTERN.fullmatch(args.sha) is None:
        raise CannotCheckError(f'{args.sha!r} is not a full 40-character commit SHA')
    token = os.environ.get('GITHUB_TOKEN')
    if not token or not args.repo:
        raise CannotCheckError('GITHUB_TOKEN and a repository (--repo or GITHUB_REPOSITORY) are required')
    return token


def main(argv: Sequence[str] | None = None) -> int:
    """Run the gate for the SHA given on the command line."""
    args = _parse_args(argv)
    try:
        token = _require_inputs(args)
        outcome = wait_for_ci(
            github_fetcher(token), args.repo, args.sha, timeout_seconds=args.timeout, interval_seconds=args.interval
        )
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    if outcome.state == 'passed':
        print(outcome.message)
        return 0
    _report_failure(outcome.message)
    return 1


if __name__ == '__main__':
    sys.exit(main())
