#!/usr/bin/env python3
"""Build a release branch: bump the version files and add an unfinished changelog entry.

Usage: ``prepare_release.py [--increment PATCH|MINOR|MAJOR] [--prerelease alpha|beta|rc]``

The script refuses to run on ``main``, when HEAD is not ``origin/main``, with a dirty tree, or when
``release/v<version>`` already exists locally or on ``origin``. It computes the version with ``cz bump --get-next``,
creates and switches to ``release/v<version>``, runs ``cz bump --files-only --yes`` (``pyproject.toml``, ``uv.lock``
and ``__init__.py``; no commit, no tag) and checks that the computed version, ``[project].version`` and
``__version__`` agree. Then it inserts a ``## v<version> (date)`` entry above the newest changelog entry.

The entry has one placeholder bullet per commit since the last ``v*`` tag that commitizen counts toward the bump, judged
by commitizen's own configured ``bump_pattern`` and ``bump_map`` over the whole message (so a ``BREAKING CHANGE:``
footer counts), plus one per conventional commit it does not bump on (``chore:``, ``docs:``), which goes under Fix. A
major release always has at least one placeholder under Upgrade notes, whether the major was forced or a commit broke
compatibility. Every placeholder sits under a gated heading (``Upgrade notes``, ``Feature`` or ``Fix``) and carries
neither a docs link nor an exemption, so the release docs gate (``check_release_docs.py``) fails until a person has
rewritten it and given it a docs link, a ``(no docs: <reason>)`` exemption, or moved it to ``Internal`` or
``Documentation``.

The script never commits, tags or pushes.
"""

from __future__ import annotations

import argparse
from collections.abc import (
    Callable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
import contextlib
import datetime
import functools
import logging
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unicodedata

from check_release_docs import (
    VERSION_HEADING_START,
    CannotCheckError,
    _scan,
    newest_version,
)
from check_version_change import (
    INIT_PATH,
    module_version,
    project_version,
    release_branch,
)


@contextlib.contextmanager
def _leave_process_state_alone() -> Iterator[None]:
    """Undo what importing commitizen does to the process: it disables every existing logger and wraps stdout."""
    streams = (sys.stdout, sys.stderr)
    disabled = {
        name: logger.disabled
        for name, logger in logging.root.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        sys.stdout, sys.stderr = streams
        for name, was_disabled in disabled.items():
            logging.getLogger(name).disabled = was_disabled


with _leave_process_state_alone():
    from commitizen import (
        config as cz_config,
        exceptions as cz_exceptions,
        factory as cz_factory,
    )
    from commitizen.version_increment import VersionIncrement

REPO_ROOT = Path(__file__).resolve().parents[1]
SECTION_ORDER = ('Upgrade notes', 'Feature', 'Fix', 'Internal', 'Documentation')
WRAP_WIDTH = 120
SHORT_SHA_LENGTH = 7
FIELD_SEPARATOR = '\x1f'
RECORD_SEPARATOR = '\x1e'
SKIPPED_TYPES = frozenset({'bump'})
SECTION_BY_INCREMENT = {
    VersionIncrement.MAJOR: 'Upgrade notes',
    VersionIncrement.MINOR: 'Feature',
    VersionIncrement.PATCH: 'Fix',
}
ORIGIN_MAIN = 'origin/main'
UNCLASSIFIED_PLACEHOLDER = (
    '- **TODO: describe this change for users.** No commit since the last tag is a conventional commit, so\n'
    '  none could be listed here. Rewrite this bullet, then end it with a docs link or a no-docs exemption in\n'
    '  parentheses, or move it to Internal or Documentation.'
)
MAJOR_PLACEHOLDER = (
    '- **TODO: describe this change for users.** This is a major release, so it needs upgrade notes. Say what\n'
    '  users must change when they upgrade, then end this bullet with a docs link or a no-docs exemption in\n'
    '  parentheses.'
)
SUMMARY_PLACEHOLDER = '**TODO: one sentence on what changes for users.**'
CZ = (sys.executable, '-m', 'commitizen')
LOG_FORMAT = '--format=%H%x1f%s%x1f%b%x1e'
NO_BUMP_EXIT_CODES = frozenset({3, 21})  # commitizen: NO_COMMITS_FOUND, NO_COMMITS_TO_BUMP
REF_NOT_FOUND_EXIT_CODE = 2  # git ls-remote --exit-code: no matching ref
UNDO_HINT = 'git restore . && git checkout - && git branch ' + '-D '


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
        sha, subject, body = record.strip('\n').split(FIELD_SEPARATOR, maxsplit=2)
        commits.append(Commit(sha=sha, subject=subject, body=body.strip()))
    return commits


@dataclass(frozen=True)
class BumpRules:
    """The rules ``cz bump`` applies to commit messages, as commitizen itself is configured."""

    pattern: str
    increments: Mapping[str, str | None]


def _rules_from(settings: cz_config.BaseConfig) -> BumpRules:
    cz = cz_factory.committer_factory(settings)
    increments = cz.bump_map_major_version_zero if settings.settings['major_version_zero'] else cz.bump_map
    if not cz.bump_pattern or not increments:
        raise ReleaseRefusedError(f'commitizen rule {settings.settings["name"]!r} does not support bump')
    return BumpRules(pattern=cz.bump_pattern, increments=increments)


@functools.cache
def default_bump_rules() -> BumpRules:
    """Return the rules of an unconfigured commitizen, which touch no file."""
    return _rules_from(cz_config.BaseConfig())


def load_bump_rules(repo: Path) -> BumpRules:
    """Return the rules commitizen applies in ``repo``: its ``pyproject.toml`` section, else commitizen's defaults."""
    try:
        settings = cz_config.read_cfg(str(repo / 'pyproject.toml'))
    except (cz_exceptions.ConfigFileNotFound, cz_exceptions.ConfigFileIsEmpty):
        return default_bump_rules()
    return _rules_from(settings)


def section_for(commit: Commit, rules: BumpRules | None = None) -> str | None:
    """Return the gated heading a commit's placeholder goes under, or ``None`` when it needs no bullet.

    Asks commitizen's configured rules what the whole message (subject and body) bumps: ``bump_pattern`` picks the
    lines, ``bump_map`` turns them into an increment, and the commit takes the highest. ``MAJOR`` goes under
    ``Upgrade notes``, ``MINOR`` under ``Feature`` and ``PATCH`` under ``Fix``. A conventional subject that commitizen
    does not bump on (``chore:``, ``docs:``) still goes under ``Fix``, so a person decides where it belongs. Version
    bumps and subjects that are not conventional get no bullet.
    """
    rules = rules or default_bump_rules()
    message = f'{commit.subject.strip()}\n\n{commit.body.strip()}'.strip()
    increment = VersionIncrement.from_message(message, rules.pattern, rules.increments)
    if increment != VersionIncrement.NONE:
        return SECTION_BY_INCREMENT[increment]
    subject_match = re.search(rules.pattern, commit.subject.strip())
    if subject_match is None or subject_match.group(1).lower() in SKIPPED_TYPES:
        return None
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


def render_entry(
    version: str,
    date: datetime.date,
    commits: Sequence[Commit],
    *,
    increment: str | None = None,
    rules: BumpRules | None = None,
) -> str:
    """Render the unfinished changelog entry for ``version``.

    A ``MAJOR`` release always has at least one placeholder under ``Upgrade notes``, so it cannot pass the docs gate
    without upgrade notes. ``increment`` is ``MAJOR`` when the release raises the major version, whether forced or
    because a commit breaks compatibility.
    """
    bullets: dict[str, list[str]] = {section: [] for section in SECTION_ORDER}
    for commit in commits:
        section = section_for(commit, rules)
        if section is not None:
            bullets[section].append(_placeholder(commit))
    if increment == 'MAJOR' and not bullets['Upgrade notes']:
        bullets['Upgrade notes'].append(MAJOR_PLACEHOLDER)
    if not any(bullets.values()):
        bullets['Fix'].append(UNCLASSIFIED_PLACEHOLDER)
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
    if '\r\n' in changelog:
        entry = entry.replace('\n', '\r\n')
    return changelog[:cut] + entry + changelog[cut:]


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
        raise ReleaseRefusedError(
            'refusing to run on main: switch to a detached HEAD at origin/main first (git switch --detach origin/main)'
        )
    status = run(('git', 'status', '--porcelain'))
    if status.returncode != 0:
        raise ReleaseRefusedError(f'cannot read the git status: {_detail(status)}')
    if status.stdout.strip():
        raise ReleaseRefusedError(f'the tree has uncommitted changes; commit or stash them first:\n{status.stdout}')
    heads = run(('git', 'rev-parse', 'HEAD', ORIGIN_MAIN))
    if heads.returncode != 0:
        raise ReleaseRefusedError(f'cannot resolve {ORIGIN_MAIN}: {_detail(heads)}')
    head, origin_main = heads.stdout.split()
    if head != origin_main:
        raise ReleaseRefusedError(
            f'HEAD is not {ORIGIN_MAIN}: a release branch must contain only the release commit. '
            f'Run git fetch origin main && git switch --detach {ORIGIN_MAIN}, then try again'
        )


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


def _current_version(repo: Path) -> str:
    try:
        return project_version((repo / 'pyproject.toml').read_text(encoding='utf-8'))
    except (CannotCheckError, OSError) as error:
        raise ReleaseRefusedError(f'cannot read the current version: {error}') from error


def _major(version: str) -> int:
    return int(re.match(r'\d+', version)[0])  # type: ignore[index]


def _bump_files(run: CommandRunner, repo: Path, version: str, flags: list[str]) -> None:
    bumped = run((*CZ, 'bump', '--files-only', '--yes', *flags))
    if bumped.returncode != 0:
        raise ReleaseRefusedError(f'cz bump --files-only failed: {_detail(bumped)}')
    _check_bumped_versions(repo, version)


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
    increment = increment.upper() if increment else None
    flags = _flags(increment, prerelease)
    _refuse_unsafe_start(run)
    current_version = _current_version(repo)
    version = _next_version(run, flags)
    branch = release_branch(version)
    _refuse_existing_branch(run, branch)
    commits = _commits_since_last_tag(run)
    changelog_path = repo / 'CHANGELOG.md'
    with changelog_path.open(encoding='utf-8', newline='') as changelog_file:
        entry = render_entry(
            version,
            today,
            commits,
            increment='MAJOR' if increment == 'MAJOR' or _major(version) > _major(current_version) else None,
            rules=load_bump_rules(repo),
        )
        new_changelog = insert_entry(changelog_file.read(), entry)
    switched = run(('git', 'switch', '-c', branch))
    if switched.returncode != 0:
        raise ReleaseRefusedError(f'cannot create {branch}: {_detail(switched)}')
    try:
        _bump_files(run, repo, version, flags)
    except ReleaseRefusedError as error:
        raise ReleaseRefusedError(f'{error}\nUndo with: {UNDO_HINT}{branch}') from error
    try:
        changelog_path.write_text(new_changelog, encoding='utf-8', newline='')
    except OSError as error:
        raise ReleaseRefusedError(f'cannot write {changelog_path}: {error}\nUndo with: {UNDO_HINT}{branch}') from error
    return PreparedRelease(version=version, branch=branch, commits=commits)


NEXT_STEPS = """\
Prepared {branch} for {version} with {count} commit(s) since the last tag. Nothing is committed, tagged or pushed.

Next:
  1. Open CHANGELOG.md: write the one-sentence summary, then rewrite every placeholder bullet. End each bullet under
     Upgrade notes, Feature or Fix with a docs link or a no-docs exemption, or move it to Internal or Documentation.
  2. If code that the cache version guards changed since the last release, add a "(cache kept: <reason>)" line
     before the first ### heading unless CACHE_VERSION or RUNNER_FIDELITY_VERSION was raised.
  3. Check it: uv run mkdocs build --strict --site-dir site
               uv run python scripts/check_release_docs.py {version} --site-dir site
  4. git add CHANGELOG.md pyproject.toml uv.lock src/pytest_gremlins/__init__.py
     git commit -S -m "bump: version {version}"
  5. git push -u origin {branch}, then open a pull request.
"""


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--increment', type=str.upper, choices=['PATCH', 'MINOR', 'MAJOR'], help='default: auto')
    parser.add_argument('--prerelease', choices=['alpha', 'beta', 'rc'], help='default: a stable release')
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    repo: Path = REPO_ROOT,
    run: CommandRunner | None = None,
    today: datetime.date | None = None,
) -> int:
    """CLI entry point; returns 0 when the branch is prepared and 1 when the script refuses."""
    args = _parse_args(argv)
    runner = run or functools.partial(run_command, cwd=repo)
    try:
        release = prepare_release(
            repo=repo,
            increment=args.increment,
            prerelease=args.prerelease,
            run=runner,
            today=today or datetime.date.today(),
        )
    except ReleaseRefusedError as error:
        print(f'prepare_release: {error}', file=sys.stderr)
        return 1
    print(NEXT_STEPS.format(branch=release.branch, version=release.version, count=len(release.commits)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
