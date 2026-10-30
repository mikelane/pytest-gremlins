#!/usr/bin/env python3
"""Release cache gate: refuse a release that changes verdict code without raising a cache marker or saying why not.

The incremental cache keeps a verdict until ``CACHE_VERSION`` or ``RUNNER_FIDELITY_VERSION`` changes. The per-PR
``Verdict Change Check`` only sees what its sample project exercises, so a verdict change outside the sample could
ship with no marker raised and leave users' warm caches returning wrong verdicts. This check runs at release time.

It compares the code being released (``HEAD``) with the previous release: the newest ``v*`` tag reachable from
``HEAD``, not counting the tag of the version being released. The files compared are the ones the cache-version
guard hashes, taken from the guard's own file-set function (``check_verdict_change.guarded_repo_paths``), never from a
second list. It passes when

* no guarded file changed since the previous release, or
* ``CACHE_VERSION`` or ``RUNNER_FIDELITY_VERSION`` differs from its value at the previous release (a lowered marker
  is rejected by ``check_verdict_change.py``, not here), or
* the release's ``CHANGELOG.md`` entry keeps the cache on purpose with a line ``(cache kept: <reason>)``.

Put the ``(cache kept: <reason>)`` line in the entry's prose, before its first ``###`` heading. It is accepted nowhere
else, because the release docs gate allows only list items under ``### Upgrade notes``, ``### Feature`` and
``### Fix``. The reason must not be empty. It is public and is reviewed in the changelog PR.

Nothing skips this check: it has no flag, environment variable or input that turns it off.

Usage: ``check_cache_kept.py VERSION`` or ``check_cache_kept.py --newest`` (the topmost changelog entry).

Exit codes: 0 when the release passes, 1 when it fails (each problem is printed on stdout with a ``PROBLEM:`` prefix,
naming the changed files), 2 when the check could not run (no previous release tag, unreadable markers or entry; the
reason is printed on stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import re
import sys

from check_release_docs import (
    CODE_SPAN,
    DEFAULT_CHANGELOG,
    CannotCheckError,
    entry_preamble,
    newest_version,
)
from check_verdict_change import (
    GIT,
    INCREMENTAL_PATH,
    RELEASE_TAG_PATTERN,
    REPO_ROOT,
    VERSIONS_PATH,
    Markers,
    _git_diff_names,
    _git_output,
    guarded_changes,
    guarded_repo_paths,
    parse_markers,
    released_markers,
)

PROBLEM_PREFIX = 'PROBLEM: '
CACHE_KEPT = re.compile(r'\(cache kept:([^)]*)\)')
LINE_FORMAT = '(cache kept: <reason>)'

__all__ = ['GIT', 'cache_kept_reasons', 'check_cache_kept', 'main', 'previous_release_tag']


def cache_kept_reasons(preamble: str) -> list[str]:
    """Return the stripped reason of every ``(cache kept: ...)`` line in ``preamble``; code spans do not count."""
    visible = CODE_SPAN.sub('', preamble)
    return [match.group(1).strip() for match in CACHE_KEPT.finditer(visible)]


def check_cache_kept(changed: Sequence[str], previous: Markers, head: Markers, preamble: str) -> list[str]:
    """Return why the release fails, one line per problem; empty when it passes.

    Args:
        changed: The guarded files that differ between the previous release and the code being released.
        previous: The cache markers at the previous release.
        head: The cache markers of the code being released.
        preamble: The changelog entry's prose before its first ``###`` heading.
    """
    if not changed or head != previous:
        return []
    reasons = cache_kept_reasons(preamble)
    if any(reasons):
        return []
    files = ', '.join(changed)
    if reasons:
        return [
            f'the {LINE_FORMAT} line has an empty reason; say why the cached verdicts stay valid after changes to '
            f'{files}'
        ]
    return [
        f'guarded code changed since the previous release ({files}), but neither CACHE_VERSION nor '
        f'RUNNER_FIDELITY_VERSION was raised. Raise one, or keep the cache on purpose with a line {LINE_FORMAT} '
        'in the changelog entry, before its first "###" heading.'
    ]


def previous_release_tag(version: str, repo: Path = REPO_ROOT) -> str | None:
    """Return the newest release tag reachable from ``HEAD``, leaving out the tag of ``version``, or ``None``."""
    tag = _git_output(
        repo,
        'describe',
        '--tags',
        '--abbrev=0',
        '--match',
        RELEASE_TAG_PATTERN,
        '--exclude',
        f'v{version.removeprefix("v")}',
        'HEAD',
    )
    return tag.strip() if tag else None


def _head_markers() -> Markers:
    versions = (REPO_ROOT / VERSIONS_PATH).read_text(encoding='utf-8')
    incremental = (REPO_ROOT / INCREMENTAL_PATH).read_text(encoding='utf-8')
    markers = parse_markers(versions, incremental)
    if markers is None:
        raise CannotCheckError(f'cannot read the cache markers from {VERSIONS_PATH} and {INCREMENTAL_PATH}')
    return markers


def _changed_guarded_files(previous_tag: str) -> list[str]:
    changed = _git_diff_names(previous_tag)
    deleted = _git_diff_names(previous_tag, '--diff-filter=D')
    return guarded_changes(changed, deleted, guarded_repo_paths())


def _read_changelog(path: Path) -> str:
    try:
        return path.read_bytes().decode('utf-8')
    except OSError as error:
        raise CannotCheckError(f'cannot read {path}: {error}') from error


def _preamble(changelog: str, version: str) -> str:
    preamble = entry_preamble(changelog, version)
    if preamble is None:
        raise CannotCheckError(f'the changelog has no "## v{version}" entry')
    return preamble


def _check(args: argparse.Namespace) -> tuple[str, list[str]]:
    changelog = _read_changelog(args.changelog)
    version: str = newest_version(changelog) if args.newest else args.version
    version = version.removeprefix('v')
    if not version:
        raise CannotCheckError('the version is empty')
    previous_tag = previous_release_tag(version)
    if previous_tag is None:
        raise CannotCheckError('no earlier release tag is reachable from HEAD; fetch tags (fetch-depth: 0)')
    previous = released_markers(previous_tag)
    if previous is None:
        raise CannotCheckError(f'cannot read the cache markers at {previous_tag}')
    changed = _changed_guarded_files(previous_tag)
    head = _head_markers()
    needs_line = bool(changed) and head == previous
    preamble = _preamble(changelog, version) if needs_line else ''
    return version, check_cache_kept(changed, previous, head, preamble)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('version', nargs='?', help='version being released, with or without the leading v')
    parser.add_argument('--newest', action='store_true', help='check the topmost entry of the changelog instead')
    parser.add_argument('--changelog', type=Path, default=DEFAULT_CHANGELOG, help='path to CHANGELOG.md')
    args = parser.parse_args(argv)
    if args.newest == (args.version is not None):
        parser.error('give exactly one of the version and --newest')
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns 0 when the release passes, 1 when it fails, 2 when the check could not run."""
    args = _parse_args(argv)
    try:
        version, problems = _check(args)
    except CannotCheckError as error:
        print(f'could not check the release cache markers: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with a failed check (exit 1) or a pass
        print(f'could not check the release cache markers: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if problems:
        print(f'{version} cannot be released with its cache markers as they are:')
        for problem in problems:
            print(f'{PROBLEM_PREFIX}{problem}')
        return 1
    print(f'The {version} release changes no guarded code, raises a cache marker, or states why it keeps the cache.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
