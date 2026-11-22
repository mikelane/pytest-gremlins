#!/usr/bin/env python3
"""Release cache-bump gate: a release that changes a cache marker is at least a minor version and says so.

Raising ``CACHE_VERSION`` or ``RUNNER_FIDELITY_VERSION`` throws away every user's warm incremental cache, so the first
run after upgrading is cold. A patch release is a promise of "safe to upgrade without noticing", and a cold cache
breaks that promise. This check runs at release time and fails the release when a marker differs from its value at the
previous release (the newest ``v*`` tag reachable from ``HEAD``, not counting the tag being released) and either

* the version is not at least a minor bump over the previous release, or
* the changelog entry has no ``### Upgrade notes`` bullet that says the cache is rebuilt once.

A version counts as at least a minor bump when its ``major.minor`` is higher than the previous release's. One more case
counts: the previous release is a prerelease of ``X.Y.0`` (a version that sorts before ``X.Y.0`` under PEP 440, such as
``1.15.0b0`` or ``1.15.0rc1.post1``) and the new version stays on ``X.Y`` without being lower than it (``1.15.0b1``,
``1.15.0``), because that prerelease already was the minor bump over the last stable release. ``1.15.0.post1`` and
``1.15.0+local`` are not prereleases. A version that is not valid PEP 440 exits 2.

A bullet says the cache is rebuilt when its visible text, in any letter case, contains both ``cache`` and ``rebuil``
("rebuilds the cache once", "the cache is rebuilt"). Raw HTML tags with their attributes, and images with their alt
text, are not visible on the rendered page and do not count; text between tags does. The check does not judge the
wording beyond that. The docs gate (``check_release_docs.py``) still requires the bullet to carry a docs link or a
``(no docs: <reason>)`` exemption.

``prepare_release.py`` applies the first rule for you: it computes at least the next minor version when a marker
changed, and refuses ``--increment PATCH`` then. The hotfix case, a patch release cut from an older tag that changes a
marker, is tracked in #1015.

Nothing skips this check: it has no flag, environment variable or input that turns it off. With ``--newest``, a topmost
entry whose tag already exists passes, like in ``check_cache_kept.py``.

Usage: ``check_cache_bump.py VERSION`` or ``check_cache_bump.py --newest`` (the topmost changelog entry).

Exit codes: 0 when the release passes, 1 when it fails (each problem is printed on stdout with a ``PROBLEM:`` prefix),
2 when the check could not run (no previous release tag, unreadable markers, version or entry; the reason is printed on
stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import re
import sys

from packaging.version import InvalidVersion, Version

from check_cache_kept import (
    _head_markers,
    _is_tagged,
    _read_changelog,
    previous_release_tag,
)
from check_release_docs import (
    DEFAULT_CHANGELOG,
    CannotCheckError,
    newest_version,
    upgrade_note_bullets,
)
from check_verdict_change import (
    Markers,
    released_markers,
)

PROBLEM_PREFIX = 'PROBLEM: '
VERSION_SHAPE = re.compile(r'\d+\.\d+\.\d+.*')

__all__ = [
    'Markers',
    'changed_markers',
    'check_cache_bump',
    'is_at_least_minor_bump',
    'main',
    'markers_changed_since_last_release',
    'says_cache_rebuilt',
]


def _parse_version(text: str) -> Version:
    """Return ``text`` as a ``Version``; raise ``CannotCheckError`` when it is not ``X.Y.Z`` or not PEP 440."""
    if VERSION_SHAPE.fullmatch(text) is None:
        raise CannotCheckError(f'cannot read "{text}" as a version of the form X.Y.Z')
    try:
        return Version(text)
    except InvalidVersion as error:
        raise CannotCheckError(f'cannot read "{text}" as a PEP 440 version: {error}') from error


def is_at_least_minor_bump(previous: str, new: str) -> bool:
    """Return whether ``new`` is at least a minor version bump over ``previous``.

    Args:
        previous: The previous release's version, without the leading ``v``.
        new: The version being released, without the leading ``v``.

    Returns:
        True when ``new`` has a higher ``major.minor``. When ``major.minor`` is equal, True exactly when ``previous``
        sorts before ``X.Y.0`` under PEP 440 (so it is a prerelease of ``X.Y.0``: ``1.15.0b0``, ``1.15.0rc1``,
        ``1.15.0.dev3``, ``1.15.0rc1.post1``) and ``new`` is not lower than ``previous``. ``1.15.0.post1``,
        ``1.15.0+local`` and ``1.15.0.post1.dev1`` sort after ``1.15.0``, so they are not prereleases.

    Raises:
        CannotCheckError: When either version is not ``X.Y.Z`` followed by a valid PEP 440 remainder.

    >>> is_at_least_minor_bump('1.15.0b0', '1.15.0')
    True
    >>> is_at_least_minor_bump('1.15.0.post1', '1.15.1')
    False
    """
    old, current = _parse_version(previous), _parse_version(new)
    if current.release[:2] != old.release[:2]:
        return current.release[:2] > old.release[:2]
    line_start = Version(f'{old.major}.{old.minor}.0')
    return old < line_start and current >= old


def says_cache_rebuilt(bullet: str) -> bool:
    """Return whether ``bullet`` mentions the cache and a rebuild, in any letter case."""
    lowered = bullet.lower()
    return 'cache' in lowered and 'rebuil' in lowered


def changed_markers(previous: Markers, head: Markers) -> list[str]:
    """Return the name of each cache marker whose value in ``head`` differs from its value in ``previous``."""
    changed: list[str] = []
    if head.cache_version != previous.cache_version:
        changed.append('CACHE_VERSION')
    if head.runner_fidelity_version != previous.runner_fidelity_version:
        changed.append('RUNNER_FIDELITY_VERSION')
    return changed


def check_cache_bump(
    previous_markers: Markers,
    head_markers: Markers,
    previous_version: str,
    version: str,
    *,
    bullets: Sequence[str],
) -> list[str]:
    """Return why the release fails, one line per problem; empty when it passes.

    Args:
        previous_markers: The cache markers at the previous release.
        head_markers: The cache markers of the code being released.
        previous_version: The previous release's version, without the leading ``v``.
        version: The version being released, without the leading ``v``.
        bullets: The text of every bullet under ``### Upgrade notes`` in the release's changelog entry.

    Returns:
        The problems, one line each, or an empty list when no marker changed or the release handles the change.
    """
    changed = changed_markers(previous_markers, head_markers)
    if not changed:
        return []
    names = ' and '.join(changed)
    problems: list[str] = []
    if not is_at_least_minor_bump(previous_version, version):
        problems.append(
            f"{names} changed since v{previous_version}, which discards users' warm caches, but {version} is not a "
            f'minor bump over {previous_version}. Release at least the next minor version.'
        )
    if not any(says_cache_rebuilt(bullet) for bullet in bullets):
        problems.append(
            f'{names} changed since v{previous_version}, but the entry has no "### Upgrade notes" bullet that says the '
            'cache is rebuilt once. Add one that mentions the cache and says it is rebuilt, for example "The first '
            'run after upgrading rebuilds the cache once."'
        )
    return problems


def markers_changed_since_last_release(repo: Path) -> tuple[str, list[str]] | None:
    """Return the previous release's version and the names of the markers that changed since it, or ``None``.

    Used by ``prepare_release.py``, which runs before any tag exists for the release it prepares, so every ``v*`` tag
    counts.

    Args:
        repo: The repository to read the tags and the markers from.

    Returns:
        ``None`` when no release tag is reachable or the markers cannot be read at it or in the working tree (a marker
        file is missing, unreadable, not UTF-8, or has no marker in it).
    """
    tag = previous_release_tag(None, repo)
    previous_markers = released_markers(tag, repo) if tag else None
    if tag is None or previous_markers is None:
        return None
    try:
        head_markers = _head_markers(repo)
    except (CannotCheckError, OSError, UnicodeDecodeError):
        return None
    return tag.removeprefix('v'), changed_markers(previous_markers, head_markers)


def _check(args: argparse.Namespace) -> tuple[str, list[str], str]:
    """Run the check for the parsed arguments; return the version checked, its problems and the message on a pass."""
    changelog = _read_changelog(args.changelog)
    version: str = newest_version(changelog) if args.newest else args.version
    version = version.removeprefix('v')
    if not version:
        raise CannotCheckError('the version is empty')
    if args.newest and _is_tagged(version):
        return (
            version,
            [],
            f'v{version} is already released; changes since then are checked when the next entry is added.',
        )
    previous_tag = previous_release_tag(None if args.newest else version)
    if previous_tag is None:
        raise CannotCheckError('no earlier release tag is reachable from HEAD; fetch tags (fetch-depth: 0)')
    previous_markers = released_markers(previous_tag)
    if previous_markers is None:
        raise CannotCheckError(f'cannot read the cache markers at {previous_tag}')
    head_markers = _head_markers()
    bullets = upgrade_note_bullets(changelog, version) if changed_markers(previous_markers, head_markers) else []
    if bullets is None:
        raise CannotCheckError(f'the changelog has no "## v{version}" entry')
    problems = check_cache_bump(
        previous_markers, head_markers, previous_tag.removeprefix('v'), version, bullets=bullets
    )
    return version, problems, f'The {version} release changes no cache marker, or is a minor release that explains it.'


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
        version, problems, pass_message = _check(args)
    except CannotCheckError as error:
        print(f'could not check the release cache bump: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with a failed check (exit 1) or a pass
        print(f'could not check the release cache bump: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if problems:
        print(f'{version} cannot be released with its cache markers as they are:')
        for problem in problems:
            print(f'{PROBLEM_PREFIX}{problem}')
        return 1
    print(pass_message)
    return 0


if __name__ == '__main__':
    sys.exit(main())
