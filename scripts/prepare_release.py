#!/usr/bin/env python3
"""Build a release branch: bump the version files and add an unfinished changelog entry.

Usage: ``prepare_release.py [--increment PATCH|MINOR|MAJOR] [--prerelease alpha|beta|rc]``

The script refuses to run on ``main``, with a dirty tree, or when ``release/v<version>`` already exists locally or on
``origin``. It computes the version with ``cz bump --get-next``, creates and switches to ``release/v<version>``, runs
``cz bump --files-only --yes`` (``pyproject.toml``, ``uv.lock`` and ``__init__.py``; no commit, no tag) and checks
that the computed version, ``[project].version`` and ``__version__`` agree. Then it inserts a
``## v<version> (date)`` entry above the newest changelog entry.

The entry has one placeholder bullet per conventional commit since the last ``v*`` tag. Every placeholder sits under
a gated heading (``Upgrade notes``, ``Feature`` or ``Fix``) and carries neither a docs link nor an exemption, so the
release docs gate (``check_release_docs.py``) fails until a person has rewritten it and given it a docs link, a
``(no docs: <reason>)`` exemption, or moved it to ``Internal`` or ``Documentation``.

The script never commits, tags or pushes.
"""

from __future__ import annotations

import argparse
from collections.abc import (
    Callable,
    Sequence,
)
from dataclasses import dataclass
import datetime
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unicodedata

from check_version_change import (
    INIT_PATH,
    module_version,
    project_version,
    release_branch,
)
from check_release_docs import (
    VERSION_HEADING_START,
    CannotCheckError,
    _scan,
    newest_version,
)

SECTION_ORDER = ('Upgrade notes', 'Feature', 'Fix', 'Internal', 'Documentation')
WRAP_WIDTH = 120
SHORT_SHA_LENGTH = 7
FIELD_SEPARATOR = '\x1f'
RECORD_SEPARATOR = '\x1e'
CONVENTIONAL_SUBJECT = re.compile(r'(?P<type>[A-Za-z]+)(?:\([^)\n]*\))?(?P<breaking>!)?: \S')
BREAKING_FOOTER = re.compile(r'^BREAKING[ -]CHANGE:', re.MULTILINE)
SKIPPED_TYPES = frozenset({'bump'})
SUMMARY_PLACEHOLDER = '**TODO: one sentence on what changes for users.**'


class ReleaseRefusedError(Exception):
    """Raised when the release cannot be prepared; the message says why and what to do."""


@dataclass(frozen=True)
class Commit:
    """A commit since the last release."""

    sha: str
    subject: str
    body: str


def parse_commit_log(raw: str) -> list[Commit]:
    """Parse ``git log --format=%H%x1f%s%x1f%b%x1e`` output."""
    commits = []
    for record in raw.split(RECORD_SEPARATOR):
        if not record.strip():
            continue
        sha, subject, body = record.strip('\n').split(FIELD_SEPARATOR)
        commits.append(Commit(sha=sha, subject=subject, body=body.strip()))
    return commits


def section_for(commit: Commit) -> str | None:
    """Return the gated heading a commit's placeholder goes under, or ``None`` when it needs no bullet."""
    match = CONVENTIONAL_SUBJECT.match(commit.subject)
    if match is None or match.group('type').lower() in SKIPPED_TYPES:
        return None
    if match.group('breaking') or BREAKING_FOOTER.search(commit.body):
        return 'Upgrade notes'
    if match.group('type').lower() == 'feat':
        return 'Feature'
    return 'Fix'


def _plain(text: str) -> str:
    """Replace every control or separator character, line breaks included, with a space."""
    spaced = ''.join(' ' if unicodedata.category(char)[0] in 'CZ' else char for char in text)
    return ' '.join(spaced.split())


def _code_span(text: str) -> str:
    longest_run = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * (longest_run + 1)
    padding = ' ' if text.startswith('`') or text.endswith('`') else ''
    return f'{fence}{padding}{text}{padding}{fence}'


def _placeholder(commit: Commit) -> str:
    text = (
        '**TODO: describe this change for users.** '
        f'Commit {_code_span(_plain(commit.subject))} ({commit.sha[:SHORT_SHA_LENGTH]}). '
        'Rewrite this bullet, then end it with a docs link or a no-docs exemption in parentheses, '
        'or move it to Internal or Documentation.'
    )
    return textwrap.fill(
        text,
        width=WRAP_WIDTH,
        initial_indent='- ',
        subsequent_indent='  ',
        break_long_words=False,
        break_on_hyphens=False,
    )


def render_entry(version: str, date: datetime.date, commits: Sequence[Commit]) -> str:
    """Render the unfinished changelog entry for ``version``."""
    bullets: dict[str, list[str]] = {section: [] for section in SECTION_ORDER}
    for commit in commits:
        section = section_for(commit)
        if section is not None:
            bullets[section].append(_placeholder(commit))
    parts = [f'## v{version} ({date.isoformat()})', SUMMARY_PLACEHOLDER]
    for section in SECTION_ORDER:
        parts.append(f'### {section}')
        if bullets[section]:
            parts.append('\n'.join(bullets[section]))
    return '\n\n'.join(parts) + '\n\n'


def insert_entry(changelog: str, entry: str) -> str:
    """Insert ``entry`` above the newest ``## v`` heading, found by the docs gate's own heading rule."""
    try:
        newest_version(changelog)
    except CannotCheckError as error:
        raise ReleaseRefusedError(f'cannot place the entry: {error}') from error
    scan = _scan(changelog)
    heading = next(line for line in scan.lines if VERSION_HEADING_START.match(line.heading))
    cut = len(''.join(scan.raw_lines[: heading.number - 1]))
    return changelog[:cut] + entry + changelog[cut:]


CZ = (sys.executable, '-m', 'commitizen')
LOG_FORMAT = '--format=%H%x1f%s%x1f%b%x1e'
NO_BUMP_EXIT_CODES = frozenset({3, 21})  # commitizen: NO_COMMITS_FOUND, NO_COMMITS_TO_BUMP
REF_NOT_FOUND_EXIT_CODE = 2  # git ls-remote --exit-code: no matching ref
UNDO_HINT = 'git restore . && git switch - && git branch ' + '-D '


@dataclass(frozen=True)
class CommandResult:
    """The outcome of one command."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def run_command(args: Sequence[str], *, cwd: Path) -> CommandResult:
    """Run ``args`` in ``cwd`` and capture its output."""
    try:
        completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        raise ReleaseRefusedError(f'cannot run {args[0]}: {error}') from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class PreparedRelease:
    """What the script did, for the next-steps message."""

    version: str
    branch: str
    commits: list[Commit]


def _detail(result: CommandResult) -> str:
    return (result.stderr.strip() or result.stdout.strip()) or f'exit {result.returncode}'


def _flags(increment: str | None, prerelease: str | None) -> list[str]:
    flags = []
    if increment:
        flags += ['--increment', increment.upper()]
    if prerelease:
        flags += ['--prerelease', prerelease]
    return flags


def _refuse_unsafe_start(run: CommandRunner) -> None:
    # A detached HEAD (a worktree at origin/main, say) has no branch name and is a fine start point.
    current = run(('git', 'symbolic-ref', '--short', '-q', 'HEAD'))
    if current.returncode == 0 and current.stdout.strip() == 'main':
        raise ReleaseRefusedError('refusing to run on main: switch to a work branch or a detached HEAD first')
    status = run(('git', 'status', '--porcelain'))
    if status.returncode != 0:
        raise ReleaseRefusedError(f'cannot read the git status: {_detail(status)}')
    if status.stdout.strip():
        raise ReleaseRefusedError(f'the tree has uncommitted changes; commit or stash them first:\n{status.stdout}')


def _next_version(run: CommandRunner, flags: list[str]) -> str:
    result = run((*CZ, 'bump', '--get-next', *flags))
    if result.returncode in NO_BUMP_EXIT_CODES:
        raise ReleaseRefusedError(
            'no commit since the last tag is eligible for a version bump '
            f'({_detail(result)}); pass --increment PATCH|MINOR|MAJOR to force one'
        )
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        raise ReleaseRefusedError(f'cz bump --get-next failed: {_detail(result)}')
    return version


def _refuse_existing_branch(run: CommandRunner, branch: str) -> None:
    if run(('git', 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}')).returncode == 0:
        raise ReleaseRefusedError(f'{branch} already exists locally; delete it or pick another increment')
    remote = run(('git', 'ls-remote', '--exit-code', '--heads', 'origin', branch))
    if remote.returncode == 0:
        raise ReleaseRefusedError(f'{branch} already exists on origin')
    if remote.returncode != REF_NOT_FOUND_EXIT_CODE:
        raise ReleaseRefusedError(f'cannot check origin for {branch}: {_detail(remote)}')


def _commits_since_last_tag(run: CommandRunner) -> list[Commit]:
    tag = run(('git', 'describe', '--tags', '--abbrev=0', '--match', 'v*'))
    span = (f'{tag.stdout.strip()}..HEAD',) if tag.returncode == 0 else ()
    log = run(('git', 'log', *span, LOG_FORMAT))
    if log.returncode != 0:
        raise ReleaseRefusedError(f'cannot read the commits since the last tag: {_detail(log)}')
    return parse_commit_log(log.stdout)


def _check_bumped_versions(repo: Path, version: str) -> None:
    try:
        in_project = project_version((repo / 'pyproject.toml').read_text(encoding='utf-8'))
        in_module = module_version((repo / INIT_PATH).read_bytes())
    except (CannotCheckError, OSError) as error:
        raise ReleaseRefusedError(f'cannot read the bumped version: {error}') from error
    if not in_project == in_module == version:
        raise ReleaseRefusedError(
            f'cz computed {version}, but pyproject.toml has {in_project} and {INIT_PATH} has {in_module}; '
            'the bump did not produce one consistent version'
        )


def prepare_release(
    *,
    repo: Path,
    increment: str | None,
    prerelease: str | None,
    run: CommandRunner,
    today: datetime.date,
) -> PreparedRelease:
    """Create ``release/v<version>``, bump the version files and write the unfinished changelog entry.

    Raises:
        ReleaseRefusedError: When the start state is unsafe, the version cannot be computed, or the bump is
            inconsistent. Nothing is changed before the branch is created.
    """
    flags = _flags(increment, prerelease)
    _refuse_unsafe_start(run)
    version = _next_version(run, flags)
    branch = release_branch(version)
    _refuse_existing_branch(run, branch)
    commits = _commits_since_last_tag(run)
    switched = run(('git', 'switch', '-c', branch))
    if switched.returncode != 0:
        raise ReleaseRefusedError(f'cannot create {branch}: {_detail(switched)}')
    bumped = run((*CZ, 'bump', '--files-only', '--yes', *flags))
    if bumped.returncode != 0:
        raise ReleaseRefusedError(
            f'cz bump --files-only failed on {branch}: {_detail(bumped)}\nUndo with: {UNDO_HINT}{branch}'
        )
    _check_bumped_versions(repo, version)
    changelog_path = repo / 'CHANGELOG.md'
    entry = render_entry(version, today, commits)
    changelog_path.write_text(insert_entry(changelog_path.read_text(encoding='utf-8'), entry), encoding='utf-8')
    return PreparedRelease(version=version, branch=branch, commits=commits)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
