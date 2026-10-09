#!/usr/bin/env python3
"""Release tag guard: verify a release tag before anything is published.

Runs on every release (tag push and manual dispatch). Checks that the tag name is safe, exists,
is annotated, and matches the ``[project].version`` recorded in ``pyproject.toml`` at the tagged
commit. Exits non-zero with a reason on stderr when any check fails; ``--name-only`` checks just
the tag name, so a workflow can validate it before fetching anything. Under GitHub Actions the
reason is printed as an ``::error`` annotation.
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


class ReleaseTagError(Exception):
    """Raised when a release tag fails verification."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, check=False)  # noqa: S607


def _text(output: bytes) -> str:
    return output.decode(errors='replace').strip()


def verify_tag_name(tag: str) -> None:
    """Reject tag names that are not a plain ``vMAJOR.MINOR.PATCH[suffix]`` string."""
    if TAG_PATTERN.fullmatch(tag) is None:
        raise ReleaseTagError(f'{tag!r} is not a valid release tag (expected e.g. v1.12.0)')


def verify_tag_is_annotated(repo: Path, tag: str) -> None:
    """Reject tags that are missing or lightweight (``--follow-tags`` ignores lightweight tags)."""
    result = _git(repo, 'cat-file', '-t', f'refs/tags/{tag}')
    if result.returncode != 0:
        reason = _text(result.stderr)
        raise ReleaseTagError(f'tag {tag} does not exist ({reason})' if reason else f'tag {tag} does not exist')
    if _text(result.stdout) != 'tag':
        raise ReleaseTagError(f'tag {tag} is not annotated (it is a lightweight tag)')


def resolve_tagged_commit(repo: Path, tag: str) -> str:
    """Return the commit SHA the tag points at, rejecting tags on a tree or blob (they cannot be checked out)."""
    result = _git(repo, 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}')
    if result.returncode != 0:
        raise ReleaseTagError(f'tag {tag} does not point at a commit')
    return _text(result.stdout)


def read_version_at_tag(repo: Path, tag: str) -> str:
    """Return ``[project].version`` from pyproject.toml as committed at the tag."""
    commit = resolve_tagged_commit(repo, tag)
    result = _git(repo, 'cat-file', '-p', f'{commit}:pyproject.toml')
    if result.returncode != 0:
        raise ReleaseTagError(f'cannot read pyproject.toml at tag {tag}: {_text(result.stderr)}')
    try:
        return str(tomllib.loads(result.stdout.decode())['project']['version'])
    except UnicodeDecodeError as error:
        raise ReleaseTagError(f'pyproject.toml at tag {tag} is not valid UTF-8: {error}') from error
    except tomllib.TOMLDecodeError as error:
        raise ReleaseTagError(f'pyproject.toml at tag {tag} is not valid TOML: {error}') from error
    except (KeyError, TypeError) as error:
        raise ReleaseTagError(f'pyproject.toml at tag {tag} has no static [project].version') from error


def verify_tag_matches_version(repo: Path, tag: str) -> None:
    """Reject tags whose name disagrees with the pyproject.toml version at that tag."""
    version = read_version_at_tag(repo, tag)
    if tag != f'v{version}':
        raise ReleaseTagError(f'tag {tag} does not match pyproject.toml version {version} (expected v{version})')


def verify_release_tag(repo: Path, tag: str) -> None:
    """Run every release tag check, raising ReleaseTagError on the first failure."""
    verify_tag_name(tag)
    verify_tag_is_annotated(repo, tag)
    verify_tag_matches_version(repo, tag)


def _report_failure(error: ReleaseTagError) -> None:
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::error title=Release tag verification failed::{error}', file=sys.stderr)
    else:
        print(f'error: {error}', file=sys.stderr)


def main() -> int:
    """Verify the tag given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--name-only', action='store_true', help='check only that the tag name is well formed')
    args = parser.parse_args()
    try:
        if args.name_only:
            verify_tag_name(args.tag)
        else:
            verify_release_tag(args.repo, args.tag)
    except ReleaseTagError as error:
        _report_failure(error)
        return 1
    print(f'Release tag {args.tag} verified')
    return 0


if __name__ == '__main__':
    sys.exit(main())
