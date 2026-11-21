#!/usr/bin/env python3
"""Dry-run release tagging: say which tag ``tag-release.yml`` would create for a push to main.

Reads ``[project].version`` from ``pyproject.toml`` and asks origin, with an exact-ref ``git ls-remote``, whether
``v<version>`` exists there. A checkout in CI is shallow and carries no tags, so only the remote can answer. When
the tag is absent it prints ``would tag v<version> at <sha>``; when it exists it prints ``v<version> already tagged``.
It never creates, pushes or dispatches anything.

Usage: ``announce_untagged_release.py --sha SHA [--repo PATH]``. The ``DRY_RUN`` environment variable must be ``true``:
the real tagging path does not exist yet, so any other value is refused rather than treated as permission.

Exit codes: 0 after printing either line; 1 when the check could not run (no readable version, a failed lookup, or
``DRY_RUN`` not ``true``), with the reason on stderr. An error is never read as "no tag", so a failure never prints
``would tag``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

TAG_PATTERN = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+[a-z0-9.]*')
REMOTE = 'origin'
LS_REMOTE_NO_MATCH = 2


class CannotCheckError(Exception):
    """Raised when the tag check could not run."""


def read_version(repo: Path) -> str:
    """Return ``[project].version`` from ``pyproject.toml``, rejecting a value that is not a plain version."""
    try:
        text = (repo / 'pyproject.toml').read_text(encoding='utf-8')
        version = tomllib.loads(text).get('project', {}).get('version')
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(f'cannot read pyproject.toml: {error}') from error
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f'pyproject.toml is not valid TOML: {error}') from error
    if not isinstance(version, str) or TAG_PATTERN.fullmatch(f'v{version}') is None:
        raise CannotCheckError(f'pyproject.toml has no usable [project].version (got {version!r})')
    return version


def tag_exists_on_origin(repo: Path, tag: str) -> bool:
    """Ask origin whether ``refs/tags/<tag>`` exists. Only exit code 2 means "not found"; anything else is an error."""
    result = subprocess.run(
        ['git', 'ls-remote', '--exit-code', '--tags', REMOTE, f'refs/tags/{tag}'],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == LS_REMOTE_NO_MATCH:
        return False
    detail = result.stderr.strip() or f'git ls-remote exited {result.returncode}'
    raise CannotCheckError(f'could not look up tag {tag} on {REMOTE}: {detail}')


def require_dry_run() -> None:
    """Refuse to run unless ``DRY_RUN`` is exactly ``true``."""
    if os.environ.get('DRY_RUN') != 'true':
        raise CannotCheckError('DRY_RUN is not "true"; only the dry run is implemented')


def announce(repo: Path, sha: str) -> str:
    """Return the line to print for the version in ``repo``."""
    require_dry_run()
    tag = f'v{read_version(repo)}'
    if tag_exists_on_origin(repo, tag):
        return f'{tag} already tagged'
    return f'would tag {tag} at {sha}'


def main() -> int:
    """Print the dry-run verdict for the checkout given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True, help='the pushed commit')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        print(announce(args.repo, args.sha))
    except CannotCheckError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
