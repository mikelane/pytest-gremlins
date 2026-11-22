#!/usr/bin/env python3
"""Tag a release commit on main and dispatch ``release.yml``: the logic behind ``tag-release.yml``.

For the pushed commit ``--sha`` the script compares ``[project].version`` with the commit's parent, then looks up
``refs/tags/v<version>`` on origin and compares the commit the tag *peels to* (an annotated tag has an object of its
own) with ``--sha``:

==========================  ======================  ===================================================
version changed vs parent   tag on origin            action
==========================  ======================  ===================================================
no                          exists                   nothing; prints ``v<version> already tagged``
no                          missing                  refuse (exit 1): a later commit holds changes the
                                                     release gates never saw
yes                         missing                  guard, release-blocker gate, annotated tag, dispatch
yes                         peels to ``--sha``       dispatch only (a re-run)
yes                         peels elsewhere          refuse (exit 1), dispatch nothing
==========================  ======================  ===================================================

Before tagging, the version guard and the blocker gate run from the *parent* commit's copy (the pre-merge main), never
from the checkout: the merged commit could have edited them. The workflow exports this script and every script it runs
from the parent into one directory and runs it from there, so the gates are the siblings of this file. A release
commit that also edits ``tag-release.yml`` is refused, because GitHub runs a push workflow from the file at the pushed
commit, so such a commit would run its own copy of the workflow. The guard-before-tag therefore closes the "release PR
dropped the guard from ci.yml" gap only for commits that leave ``tag-release.yml`` alone; a commit that rewrites the
workflow is stopped only by review of that change.

The release-blocker gate (``check_no_release_blockers.py``) runs before the tag exists. The docs, cache and wip gates
are not repeated here: ``verify-tag`` in ``release.yml`` runs them before anything is published.

Usage: ``tag_release.py --sha SHA [--repo PATH] [--github-repository OWNER/NAME]``. Needs ``GH_TOKEN`` (and
``GITHUB_TOKEN`` for the blocker gate) in the environment.

Exit codes: 0 done; 1 refused (a rule was broken, with the reason on stderr); 2 the check could not run (a failed
lookup, an unreadable version, an API error). An error is never read as "no tag", so a failure never tags.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

CANONICAL_VERSION = re.compile(
    r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
    r'((a|b|rc)(0|[1-9][0-9]*))?'
    r'(\.post(0|[1-9][0-9]*))?'
    r'(\.dev(0|[1-9][0-9]*))?'
)
REMOTE = 'origin'
WORKFLOW_PATH = '.github/workflows/tag-release.yml'
TAGGER = {'name': 'github-actions[bot]', 'email': '41898282+github-actions[bot]@users.noreply.github.com'}
SCRIPTS_DIR = Path(__file__).resolve().parent
EXIT_REFUSED = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(Exception):
    """Raised when a check could not run; the run fails closed (exit 2)."""


class ReleaseRefusedError(Exception):
    """Raised when a release rule is broken; nothing is tagged or dispatched (exit 1)."""


class Action(Enum):
    """What the pushed commit calls for."""

    ALREADY_TAGGED = 'already tagged'
    REFUSE_UNTAGGED = 'refuse: version unchanged and untagged'
    TAG_AND_DISPATCH = 'tag and dispatch'
    DISPATCH_ONLY = 'dispatch only'
    REFUSE_TAGGED_ELSEWHERE = 'refuse: tag on another commit'


@dataclass(frozen=True)
class Effects:
    """Everything that talks to GitHub or runs a gate script, so tests can replace it."""

    head_ref: Callable[[str], str]
    run_guard: Callable[[str, str], None]
    run_blocker_gate: Callable[[], None]
    create_tag: Callable[[str, str], None]
    dispatch: Callable[[str], None]


def decide(*, version_changed: bool, tag_commit: str | None, sha: str) -> Action:
    """Map the state table onto an action.

    Args:
        version_changed: Whether ``[project].version`` differs from the commit's parent.
        tag_commit: The commit ``v<version>`` peels to on origin, or None when the tag is missing.
        sha: The pushed commit.

    Returns:
        The action the state table prescribes.
    """
    if not version_changed:
        return Action.ALREADY_TAGGED if tag_commit is not None else Action.REFUSE_UNTAGGED
    if tag_commit is None:
        return Action.TAG_AND_DISPATCH
    return Action.DISPATCH_ONLY if tag_commit == sha else Action.REFUSE_TAGGED_ELSEWHERE


def parse_version(pyproject_text: str, source: str) -> str:
    """Return ``[project].version`` from ``pyproject_text``, rejecting a value that is not a canonical PEP 440 release.

    Args:
        pyproject_text: The contents of ``pyproject.toml``.
        source: Where the text came from, for error messages (for example ``HEAD^``).

    Returns:
        The version string, for example ``1.15.0b0``.

    Raises:
        CannotCheckError: If the TOML is invalid, ``[project]`` is not a table, or the version is missing, not a string
            or not canonical.
    """
    try:
        project = tomllib.loads(pyproject_text).get('project', {})
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f'pyproject.toml at {source} is not valid TOML: {error}') from error
    if not isinstance(project, dict):
        raise CannotCheckError(f'pyproject.toml at {source} has no usable [project] table (got {project!r})')
    version = project.get('version')
    if not isinstance(version, str) or CANONICAL_VERSION.fullmatch(version) is None:
        raise CannotCheckError(f'pyproject.toml at {source} has no usable [project].version (got {version!r})')
    return version


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_output(repo: Path, *args: str) -> str:
    completed = _git(repo, *args)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f'exit {completed.returncode}'
        raise CannotCheckError(f'git {" ".join(args)} failed: {detail}')
    return completed.stdout


def version_at(repo: Path, rev: str) -> str:
    """Return ``[project].version`` as committed at ``rev``.

    Raises:
        CannotCheckError: If ``rev`` does not exist, has no ``pyproject.toml`` or holds an unusable version.
    """
    return parse_version(_git_output(repo, 'show', f'{rev}:pyproject.toml'), rev)


def parent_of(repo: Path, sha: str) -> str:
    """Return the first parent of ``sha``.

    Raises:
        CannotCheckError: If ``sha`` has no parent in this checkout (an initial commit, or a checkout too shallow).
    """
    completed = _git(repo, 'rev-parse', '--verify', '--quiet', f'{sha}^')
    parent = completed.stdout.strip()
    if completed.returncode != 0 or not parent:
        raise CannotCheckError(f'{sha} has no parent in this checkout; fetch at least two commits (fetch-depth: 2)')
    return parent


def tag_commit_on_origin(repo: Path, tag: str) -> str | None:
    """Return the commit ``refs/tags/<tag>`` peels to on origin, or None when the tag does not exist.

    An annotated tag has an object of its own, which ``git ls-remote`` lists next to the peeled commit (the ``^{}``
    line); a lightweight tag lists the commit directly. ``ls-remote`` tail-matches patterns, so only exact refs count.

    Raises:
        CannotCheckError: If the lookup fails for any reason.
    """
    listing = _git(repo, 'ls-remote', '--tags', REMOTE, f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if listing.returncode != 0:
        detail = listing.stderr.strip() or f'git ls-remote exited {listing.returncode}'
        raise CannotCheckError(f'could not look up tag {tag} on {REMOTE}: {detail}')
    refs: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        object_name, _, ref = line.partition('\t')
        refs[ref] = object_name
    return refs.get(f'refs/tags/{tag}^{{}}') or refs.get(f'refs/tags/{tag}')


def changed_paths(repo: Path, parent: str, sha: str) -> set[str]:
    """Return the paths ``sha`` changes relative to ``parent``."""
    return set(_git_output(repo, 'diff', '--name-only', '--no-renames', parent, sha).splitlines())


def head_ref_from_pulls(pulls_json: str, repository: str) -> str:
    """Return the head branch of the one merged pull request from this repository in a commit-pulls answer.

    Args:
        pulls_json: The body of ``GET /repos/{owner}/{repo}/commits/{sha}/pulls``.
        repository: ``OWNER/NAME`` of this repository; a pull request from a fork does not count.

    Raises:
        CannotCheckError: If the answer is not a JSON list.
        ReleaseRefusedError: If the number of merged same-repository pull requests is not exactly one.
    """
    try:
        pulls = json.loads(pulls_json)
    except json.JSONDecodeError as error:
        raise CannotCheckError(f'the pull request lookup did not return JSON: {error}') from error
    if not isinstance(pulls, list):
        raise CannotCheckError(f'the pull request lookup did not return a list (got {type(pulls).__name__})')
    refs = [
        pull['head']['ref']
        for pull in pulls
        if isinstance(pull, dict)
        and pull.get('merged_at')
        and ((pull.get('head') or {}).get('repo') or {}).get('full_name') == repository
    ]
    if len(refs) != 1:
        raise ReleaseRefusedError(
            f'expected exactly one merged pull request from {repository} for this commit, found {len(refs)}'
        )
    return str(refs[0])


def tag_object_payload(tag: str, sha: str) -> dict[str, object]:
    """Return the body of ``POST /repos/{owner}/{repo}/git/tags`` for an annotated tag on ``sha``."""
    return {'tag': tag, 'message': f'Release {tag}', 'object': sha, 'type': 'commit', 'tagger': dict(TAGGER)}


def guard_command(repo: Path, sha: str, branch: str) -> list[str]:
    """Return the command that runs the version guard sitting next to this script, against ``sha`` and its parent.

    The workflow exports this script and the guard from the parent commit into one directory, so the sibling copy is
    the pre-merge main's. ``-E -s`` ignores the environment and the user site, as the ``release-pr`` job does.
    """
    guard = SCRIPTS_DIR / 'check_version_change.py'
    return [sys.executable, '-E', '-s', str(guard), '--repo', str(repo), '--base-ref', f'{sha}^', '--branch', branch]


def blocker_command() -> list[str]:
    """Return the command that runs the release-blocker gate sitting next to this script."""
    return [sys.executable, '-E', '-s', str(SCRIPTS_DIR / 'check_no_release_blockers.py')]


def _raise_for_status(name: str, status: int) -> None:
    if status == 0:
        return
    if status == EXIT_REFUSED:
        raise ReleaseRefusedError(f'{name} refused the release (exit 1); see its output above')
    raise CannotCheckError(f'{name} could not run (exit {status}); see its output above')


def release(repo: Path, sha: str, effects: Effects) -> str:
    """Apply the state table to the pushed commit ``sha`` of the checkout ``repo``.

    Returns:
        The line to print on success.

    Raises:
        ReleaseRefusedError: If a release rule is broken.
        CannotCheckError: If a lookup or gate could not run.
    """
    parent = parent_of(repo, sha)
    version = version_at(repo, sha)
    tag = f'v{version}'
    version_changed = version != version_at(repo, parent)
    if version_changed and WORKFLOW_PATH in changed_paths(repo, parent, sha):
        raise ReleaseRefusedError(
            f'{sha} changes the version and edits {WORKFLOW_PATH}; a push runs the workflow file from the pushed '
            'commit, so the guard could be skipped. Release from a commit that leaves the workflow alone.'
        )
    action = decide(version_changed=version_changed, tag_commit=tag_commit_on_origin(repo, tag), sha=sha)
    if action is Action.ALREADY_TAGGED:
        return f'{tag} already tagged'
    if action is Action.REFUSE_UNTAGGED:
        raise ReleaseRefusedError(
            f'{tag} is not tagged and {sha} did not change the version. The commit that changed it was never tagged, '
            'and a later commit holds changes the release gates never saw. Tag nothing; cut a new release instead.'
        )
    if action is Action.REFUSE_TAGGED_ELSEWHERE:
        raise ReleaseRefusedError(f'{tag} already exists on origin and points at another commit than {sha}')
    if action is Action.DISPATCH_ONLY:
        effects.dispatch(tag)
        return f'{tag} already tagged at {sha}; dispatched release.yml'
    effects.run_guard(sha, effects.head_ref(sha))
    effects.run_blocker_gate()
    effects.create_tag(tag, sha)
    effects.dispatch(tag)
    return f'tagged {tag} at {sha} and dispatched release.yml'


def _gh(*args: str, stdin: str | None = None) -> str:
    completed = subprocess.run(
        ['gh', *args],  # noqa: S607
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f'exit {completed.returncode}'
        raise CannotCheckError(f'gh {" ".join(args[:3])} failed: {detail}')
    return completed.stdout


def github_effects(repo: Path, repository: str) -> Effects:
    """Return the effects that call GitHub and run the gate scripts for real."""

    def head_ref(sha: str) -> str:
        return head_ref_from_pulls(_gh('api', f'repos/{repository}/commits/{sha}/pulls'), repository)

    def run_guard(sha: str, branch: str) -> None:
        _raise_for_status(
            'the version guard',
            subprocess.run(guard_command(repo, sha, branch), cwd=SCRIPTS_DIR, check=False).returncode,
        )

    def run_blocker_gate() -> None:
        _raise_for_status(
            'the release-blocker gate', subprocess.run(blocker_command(), cwd=SCRIPTS_DIR, check=False).returncode
        )

    def create_tag(tag: str, sha: str) -> None:
        created = json.loads(
            _gh(
                'api',
                '--method',
                'POST',
                f'repos/{repository}/git/tags',
                '--input',
                '-',
                stdin=json.dumps(tag_object_payload(tag, sha)),
            )
        )
        ref = {'ref': f'refs/tags/{tag}', 'sha': created['sha']}
        _gh('api', '--method', 'POST', f'repos/{repository}/git/refs', '--input', '-', stdin=json.dumps(ref))

    def dispatch(tag: str) -> None:
        _gh('workflow', 'run', 'release.yml', '--repo', repository, '--ref', 'main', '-f', f'tag={tag}')

    return Effects(head_ref, run_guard, run_blocker_gate, create_tag, dispatch)


def main(argv: list[str] | None = None) -> int:
    """Run the release step for the commit given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True, help='the pushed commit')
    parser.add_argument('--repo', type=Path, default=Path.cwd(), help='the checkout (needs the commit and its parent)')
    parser.add_argument('--github-repository', default=os.environ.get('GITHUB_REPOSITORY'), help='OWNER/NAME')
    args = parser.parse_args(argv)
    if not args.github_repository:
        print('error: --github-repository or GITHUB_REPOSITORY is required', file=sys.stderr)
        return EXIT_CANNOT_CHECK
    try:
        print(release(args.repo, args.sha, github_effects(args.repo, args.github_repository)))
    except ReleaseRefusedError as error:
        print(f'error: {error}', file=sys.stderr)
        return EXIT_REFUSED
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return EXIT_CANNOT_CHECK
    return 0


if __name__ == '__main__':
    sys.exit(main())
