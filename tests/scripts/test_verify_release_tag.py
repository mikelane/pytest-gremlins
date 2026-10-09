"""Tests for scripts/verify_release_tag.py -- release tag guard for manually dispatched releases."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_release_tag.py'

GIT_ENV_ARGS = ('-c', 'user.name=Test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false')


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', *GIT_ENV_ARGS, *args], cwd=repo, check=True, capture_output=True, text=True)  # noqa: S607


def _make_repo(tmp_path: Path, version: str = '1.2.3') -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '--quiet')
    (repo / 'pyproject.toml').write_text(f'[project]\nname = "demo"\nversion = "{version}"\n')
    _git(repo, 'add', 'pyproject.toml')
    _git(repo, 'commit', '--quiet', '-m', 'init')
    return repo


def _run_guard(repo: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag, '--repo', str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeAcceptedTags:
    def it_accepts_an_annotated_tag_matching_the_pyproject_version(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 0, result.stderr

    def it_accepts_a_prerelease_tag_matching_the_pyproject_version(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.3.0b1')
        _git(repo, 'tag', '-a', 'v1.3.0b1', '-m', 'release')

        result = _run_guard(repo, 'v1.3.0b1')

        assert result.returncode == 0, result.stderr

    def it_reads_the_version_from_the_tagged_commit_not_the_working_tree(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')
        (repo / 'pyproject.toml').write_text('[project]\nname = "demo"\nversion = "9.9.9"\n')
        _git(repo, 'commit', '--quiet', '-am', 'bump')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 0, result.stderr


@pytest.mark.medium
class DescribeRejectedTags:
    @pytest.mark.parametrize(
        'tag',
        ['1.2.3', 'v1.2', 'v1.2.3; rm -rf /', 'v1.2.3 && echo hi', '$(id)', 'v1.2.3\nv1.2.4', '../v1.2.3', ''],
    )
    def it_rejects_a_tag_with_an_unsafe_or_malformed_name(self, tmp_path: Path, tag: str) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, tag)

        assert result.returncode == 1
        assert 'not a valid release tag' in result.stderr

    def it_rejects_a_tag_that_does_not_exist(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'does not exist' in result.stderr

    def it_rejects_a_lightweight_tag(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', 'v1.2.3')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'not annotated' in result.stderr

    def it_rejects_a_tag_that_does_not_match_the_pyproject_version(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', '-a', 'v1.2.4', '-m', 'release')

        result = _run_guard(repo, 'v1.2.4')

        assert result.returncode == 1
        assert 'pyproject.toml version 1.2.3' in result.stderr
