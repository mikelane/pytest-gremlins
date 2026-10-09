"""Tests for scripts/verify_release_tag.py -- the guard that runs on every release (tag push and dispatch)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_release_tag.py'

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
ISOLATED_GIT_ENV = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
ENV_WITHOUT_GITHUB_ACTIONS = {key: value for key, value in os.environ.items() if key != 'GITHUB_ACTIONS'}


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location('verify_release_tag', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', *GIT_CONFIG_ARGS, *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=ISOLATED_GIT_ENV,
    )
    return result.stdout


def _make_repo_with_pyproject(tmp_path: Path, pyproject: str | bytes) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '--quiet')
    pyproject_bytes = pyproject if isinstance(pyproject, bytes) else pyproject.encode()
    (repo / 'pyproject.toml').write_bytes(pyproject_bytes)
    _git(repo, 'add', 'pyproject.toml')
    _git(repo, 'commit', '--quiet', '-m', 'init')
    return repo


def _make_repo_without_pyproject(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '--quiet')
    (repo / 'README.md').write_text('demo\n')
    _git(repo, 'add', 'README.md')
    _git(repo, 'commit', '--quiet', '-m', 'init')
    return repo


def _make_repo(tmp_path: Path, version: str = '1.2.3') -> Path:
    return _make_repo_with_pyproject(tmp_path, f'[project]\nname = "demo"\nversion = "{version}"\n')


def _run_guard(
    repo: Path, tag: str, *flags: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *flags, tag, '--repo', str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=ENV_WITHOUT_GITHUB_ACTIONS if env is None else env,
    )


@pytest.mark.medium
class DescribeAcceptedTags:
    def it_accepts_an_annotated_tag_matching_the_pyproject_version(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 0, result.stderr

    def it_reports_the_verified_tag(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.stdout.strip() == 'Release tag v1.2.3 verified'

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

    def it_includes_gits_reason_when_the_tag_does_not_exist(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')

        result = _run_guard(repo, 'v1.2.3')

        assert 'tag v1.2.3 does not exist (' in result.stderr
        assert 'Not a valid object name' in result.stderr

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


@pytest.mark.medium
class DescribeUnreadablePyproject:
    def it_reports_a_clean_error_when_pyproject_has_no_project_version(self, tmp_path: Path) -> None:
        repo = _make_repo_with_pyproject(tmp_path, '[project]\nname = "demo"\ndynamic = ["version"]\n')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert result.stderr.startswith('error:')
        assert 'no static [project].version' in result.stderr
        assert 'Traceback' not in result.stderr

    def it_reports_a_clean_error_when_project_is_not_a_table(self, tmp_path: Path) -> None:
        repo = _make_repo_with_pyproject(tmp_path, 'project = "x"\n')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'no static [project].version' in result.stderr
        assert 'Traceback' not in result.stderr

    def it_reports_a_clean_error_when_pyproject_is_malformed_toml(self, tmp_path: Path) -> None:
        repo = _make_repo_with_pyproject(tmp_path, '[project\nversion = "1.2.3"\n')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert result.stderr.startswith('error:')
        assert 'not valid TOML' in result.stderr
        assert 'Traceback' not in result.stderr

    def it_reports_a_clean_error_when_pyproject_is_not_utf8(self, tmp_path: Path) -> None:
        repo = _make_repo_with_pyproject(tmp_path, b'[project]\nname = "\xff\xfe"\nversion = "1.2.3"\n')
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'not valid UTF-8' in result.stderr
        assert 'Traceback' not in result.stderr

    def it_reports_a_clean_error_when_the_tagged_commit_has_no_pyproject(self, tmp_path: Path) -> None:
        repo = _make_repo_without_pyproject(tmp_path)
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release')

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'cannot read pyproject.toml' in result.stderr
        assert 'Traceback' not in result.stderr


@pytest.mark.medium
class DescribeTagsThatDoNotPointAtACommit:
    def it_rejects_an_annotated_tag_that_points_at_a_tree_instead_of_a_commit(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, '1.2.3')
        tree = _git(repo, 'rev-parse', 'HEAD^{tree}').strip()
        _git(repo, 'tag', '-a', 'v1.2.3', '-m', 'release', tree)

        result = _run_guard(repo, 'v1.2.3')

        assert result.returncode == 1
        assert 'does not point at a commit' in result.stderr


@pytest.mark.medium
class DescribeFailureReporting:
    def it_prints_a_plain_error_outside_github_actions(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, 'not-a-tag')

        assert result.stderr.startswith('error: ')
        assert '::error' not in result.stderr

    def it_prints_a_github_error_annotation_inside_github_actions(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, 'not-a-tag', env={**ENV_WITHOUT_GITHUB_ACTIONS, 'GITHUB_ACTIONS': 'true'})

        assert result.returncode == 1
        assert result.stderr.startswith('::error title=Release tag verification failed::')
        assert 'not a valid release tag' in result.stderr

    def it_escapes_a_percent_sign_in_the_annotation_message(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, 'v1.2.3%0A', env={**ENV_WITHOUT_GITHUB_ACTIONS, 'GITHUB_ACTIONS': 'true'})

        assert "'v1.2.3%250A' is not a valid release tag" in result.stderr


@pytest.mark.small
class DescribeAnnotationEscaping:
    @pytest.mark.parametrize(
        ('message', 'escaped'),
        [('100%', '100%25'), ('a\rb', 'a%0Db'), ('a\nb', 'a%0Ab'), ('%0A\n', '%250A%0A')],
    )
    def it_escapes_workflow_command_characters(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], message: str, escaped: str
    ) -> None:
        monkeypatch.setenv('GITHUB_ACTIONS', 'true')

        guard = _load_guard()

        guard._report_failure(guard.ReleaseTagError(message))

        assert capsys.readouterr().err == f'::error title=Release tag verification failed::{escaped}\n'


@pytest.mark.medium
class DescribeNameOnlyMode:
    def it_accepts_a_valid_name_without_the_tag_existing(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, 'v1.2.3', '--name-only')

        assert result.returncode == 0, result.stderr

    def it_rejects_an_invalid_name(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_guard(repo, 'v1.2; rm -rf /', '--name-only')

        assert result.returncode == 1
        assert 'not a valid release tag' in result.stderr
