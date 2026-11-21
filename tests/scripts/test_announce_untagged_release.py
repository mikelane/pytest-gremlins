"""Tests for scripts/announce_untagged_release.py -- the dry-run step of tag-release.yml."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'announce_untagged_release.py'
SHA = '0123456789abcdef0123456789abcdef01234567'  # pragma: allowlist secret

GIT_CONFIG_ARGS = (
    '-c',
    'user.name=Test',
    '-c',
    'user.email=test@example.com',
    '-c',
    'commit.gpgsign=false',
    '-c',
    'tag.gpgSign=false',
)
# COVERAGE_PROCESS_START is dropped so no child process starts a coverage run of its own.
ISOLATED_GIT_ENV = {
    **{key: value for key, value in os.environ.items() if key != 'COVERAGE_PROCESS_START'},
    'GIT_CONFIG_GLOBAL': os.devnull,
    'GIT_CONFIG_NOSYSTEM': '1',
}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', *GIT_CONFIG_ARGS, *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=ISOLATED_GIT_ENV,
    )
    return result.stdout


def _pyproject(version: str) -> str:
    return f'[project]\nname = "demo"\nversion = "{version}"\n'


def _make_clone(tmp_path: Path, pyproject: str) -> tuple[Path, Path]:
    """Return ``(origin, clone)``: a bare origin and a working clone whose pyproject.toml is ``pyproject``."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
    (clone / 'pyproject.toml').write_text(pyproject)
    _git(clone, 'add', 'pyproject.toml')
    _git(clone, 'commit', '--quiet', '-m', 'init')
    _git(clone, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main')
    return origin, clone


def _tag_on_origin_only(clone: Path, tag: str) -> None:
    _git(clone, 'tag', '-a', tag, '-m', 'release')
    _git(clone, 'push', '--quiet', 'origin', f'refs/tags/{tag}')
    _git(clone, 'tag', '-d', tag)


def _shallow_clone(tmp_path: Path, origin: Path) -> Path:
    shallow = tmp_path / 'shallow'
    _git(tmp_path, 'clone', '--quiet', '--depth', '1', '--no-tags', '--branch', 'main', origin.as_uri(), str(shallow))
    return shallow


def _run(repo: Path, *, dry_run: str | None = 'true') -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in ISOLATED_GIT_ENV.items() if key not in {'DRY_RUN', 'COVERAGE_PROCESS_START'}}
    if dry_run is not None:
        env['DRY_RUN'] = dry_run
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--repo', str(repo), '--sha', SHA],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.medium
class DescribeAnUntaggedVersion:
    def it_announces_the_tag_it_would_create(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))

        result = _run(clone)

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [f'would tag v1.2.3 at {SHA}']

    def it_announces_a_prerelease_version(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.15.0b0'))

        result = _run(clone)

        assert result.stdout.splitlines() == [f'would tag v1.15.0b0 at {SHA}']

    def it_announces_when_only_a_longer_tag_shares_the_prefix(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.14.3'))
        _tag_on_origin_only(clone, 'v1.14.30')

        result = _run(clone)

        assert result.stdout.splitlines() == [f'would tag v1.14.3 at {SHA}']

    def it_announces_when_only_a_prerelease_tag_of_the_same_base_exists(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.14.3'))
        _tag_on_origin_only(clone, 'v1.14.3b0')

        result = _run(clone)

        assert result.stdout.splitlines() == [f'would tag v1.14.3 at {SHA}']


@pytest.mark.medium
class DescribeATaggedVersion:
    def it_stays_silent_about_tagging_when_the_tag_is_on_origin(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _tag_on_origin_only(clone, 'v1.2.3')

        result = _run(clone)

        assert result.returncode == 0, result.stderr
        assert 'would tag' not in result.stdout + result.stderr

    def it_reports_that_the_version_is_already_tagged(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _tag_on_origin_only(clone, 'v1.2.3')

        result = _run(clone)

        assert result.stdout.splitlines() == ['v1.2.3 already tagged']

    def it_finds_a_tag_that_exists_only_on_origin_from_a_shallow_clone(self, tmp_path: Path) -> None:
        origin, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _tag_on_origin_only(clone, 'v1.2.3')
        shallow = _shallow_clone(tmp_path, origin)

        result = _run(shallow)

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ['v1.2.3 already tagged']

    def it_finds_a_lightweight_tag(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _git(clone, 'push', '--quiet', 'origin', 'HEAD:refs/tags/v1.2.3')

        result = _run(clone)

        assert result.stdout.splitlines() == ['v1.2.3 already tagged']


@pytest.mark.medium
class DescribeAFailedLookup:
    def it_fails_without_announcing_when_origin_is_unreachable(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _git(clone, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))

        result = _run(clone)

        assert result.returncode == 1, result.stderr
        assert 'would tag' not in result.stdout + result.stderr

    def it_names_the_failed_lookup_on_stderr(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _git(clone, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))

        result = _run(clone)

        assert 'could not look up tag v1.2.3 on origin' in result.stderr


@pytest.mark.medium
class DescribeAnUnreadableVersion:
    @pytest.mark.parametrize(
        'pyproject',
        [
            pytest.param('[project]\nname = "demo"\n', id='missing-version'),
            pytest.param('[project]\nversion = 3\n', id='non-string-version'),
            pytest.param('[project\nversion = "1.2.3"\n', id='invalid-toml'),
            pytest.param('[project]\nversion = "1.2.3\\nrefs/heads/*"\n', id='unsafe-characters'),
            pytest.param('[project]\nversion = "latest"\n', id='not-a-version'),
            pytest.param('[project]\nversion = "v1.2.3"\n', id='leading-v'),
            pytest.param('[project]\nversion = " 1.2.3"\n', id='leading-space'),
            pytest.param('[project]\nversion = "01.2.3"\n', id='leading-zero'),
            pytest.param('[project]\nversion = ""\n', id='empty-string'),
        ],
    )
    def it_fails_without_announcing(self, tmp_path: Path, pyproject: str) -> None:
        _, clone = _make_clone(tmp_path, pyproject)

        result = _run(clone)

        assert result.returncode == 1, result.stderr
        assert 'would tag' not in result.stdout + result.stderr

    @pytest.mark.parametrize(
        'pyproject',
        [
            pytest.param('project = "x"\n', id='project-is-a-string'),
            pytest.param('project = [1]\n', id='project-is-an-array'),
        ],
    )
    def it_reports_a_project_that_is_not_a_table(self, tmp_path: Path, pyproject: str) -> None:
        _, clone = _make_clone(tmp_path, pyproject)

        result = _run(clone)

        assert result.returncode == 1
        assert 'error:' in result.stderr
        assert '[project]' in result.stderr
        assert 'Traceback' not in result.stderr
        assert 'would tag' not in result.stdout

    def it_fails_when_pyproject_is_missing(self, tmp_path: Path) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        (clone / 'pyproject.toml').unlink()

        result = _run(clone)

        assert result.returncode == 1, result.stderr
        assert 'would tag' not in result.stdout + result.stderr


@pytest.mark.medium
class DescribeTheDryRunSwitch:
    @pytest.mark.parametrize('dry_run', [None, 'false', ''])
    def it_refuses_to_run_unless_dry_run_is_true(self, tmp_path: Path, dry_run: str | None) -> None:
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))

        result = _run(clone, dry_run=dry_run)

        assert result.returncode == 1, result.stderr
        assert 'would tag' not in result.stdout + result.stderr


@pytest.mark.medium
class DescribeALookalikeTagOnOrigin:
    def it_announces_when_only_a_nested_tag_ends_with_the_tag_name(self, tmp_path: Path) -> None:
        # git ls-remote patterns tail-match, so refs/tags/v1.2.3 also matches refs/tags/old/refs/tags/v1.2.3.
        _, clone = _make_clone(tmp_path, _pyproject('1.2.3'))
        _git(clone, 'push', '--quiet', 'origin', 'HEAD:refs/tags/old/refs/tags/v1.2.3')

        result = _run(clone)

        assert result.stdout.splitlines() == [f'would tag v1.2.3 at {SHA}']


@pytest.mark.medium
class DescribeAVersionThatCannotBeTagged:
    @pytest.mark.parametrize('version', ['1.2.3.', '1.2.3..4', '1.2.3.lock', '1.2.3abc'])
    def it_fails_without_announcing(self, tmp_path: Path, version: str) -> None:
        _, clone = _make_clone(tmp_path, _pyproject(version))

        result = _run(clone)

        assert result.returncode == 1, result.stderr
        assert 'would tag' not in result.stdout
