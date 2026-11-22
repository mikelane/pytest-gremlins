"""Tests that the ``release-pr`` guard step runs the base branch's copy of the guard (issue #1049).

A pull request that edits ``scripts/check_version_change.py`` must not be checked by its own edited copy, or it
could weaken the guard that is meant to stop it. The step exports the guard from ``origin/$BASE_REF`` and runs that
copy in isolation against the pull request checkout.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'
GUARD_FILES = ('check_version_change.py', 'check_release_docs.py')
ALWAYS_PASSES = 'raise SystemExit(0)\n'
POSIX_ONLY = pytest.mark.skipif(sys.platform == 'win32', reason='the step runs in bash on ubuntu-latest')
NEEDS_TOOLS = pytest.mark.skipif(
    shutil.which('uv') is None or shutil.which('git') is None or shutil.which('bash') is None,
    reason='the step needs uv, git and bash',
)
GUARD_FAILED = 1
GUARD_COULD_NOT_RUN = 2


def _guard_step() -> dict[str, Any]:
    steps = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))['jobs']['release-pr']['steps']
    return next(step for step in steps if step.get('id') == 'guard')


def _run_text() -> str:
    run: str = _guard_step()['run']
    return run


@pytest.mark.medium
class DescribeGuardStepRunsTheBaseCopy:
    def it_exports_each_guard_file_from_the_base_branch_with_git_show(self) -> None:
        assert 'for script in check_version_change.py check_release_docs.py; do' in _run_text()
        assert (
            'git -C "$GITHUB_WORKSPACE" show "origin/$BASE_REF:scripts/$script" > "$guard_dir/$script"' in _run_text()
        )

    def it_runs_the_exported_copy_against_the_pull_request_checkout(self) -> None:
        assert '--repo "$GITHUB_WORKSPACE"' in _run_text()
        assert '"$guard_dir/check_version_change.py"' in _run_text()

    def it_exports_into_a_fresh_directory_under_the_runner_temp_directory(self) -> None:
        assert 'mktemp -d "$RUNNER_TEMP/' in _run_text()

    def it_isolates_the_interpreter_from_environment_and_user_site(self) -> None:
        assert '"$python" -E -s "$guard_dir/check_version_change.py"' in _run_text()

    def it_finds_a_system_python_that_ignores_the_checkout_virtual_environment(self) -> None:
        assert 'uv python find --no-project --system "$UV_PYTHON"' in _run_text()

    @pytest.mark.parametrize(
        'forbidden', ['uv run', 'python scripts/check_version_change.py', ' scripts/check_version_change.py']
    )
    def it_never_runs_the_guard_from_the_pull_request_checkout(self, forbidden: str) -> None:
        run_lines = [line for line in _run_text().splitlines() if not line.lstrip().startswith('#')]

        assert [line for line in run_lines if forbidden in line and 'git ' not in line] == []

    def it_fails_on_any_error_and_unset_variable(self) -> None:
        assert 'set -euo pipefail' in _run_text()

    def it_keeps_the_base_ref_and_the_output_file_arguments(self) -> None:
        assert '--base-ref "origin/$BASE_REF"' in _run_text()
        assert '--github-output "$GITHUB_OUTPUT"' in _run_text()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, 'add', '--all')
    _git(repo, 'commit', '-q', '-m', message)


def _make_checkout(tmp_path: Path, *, base_has: tuple[str, ...] = GUARD_FILES) -> Path:
    repo = tmp_path / 'workspace'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    (repo / 'scripts').mkdir()
    for script in base_has:
        shutil.copy(REPO_ROOT / 'scripts' / script, repo / 'scripts' / script)
    _write(repo, 'pyproject.toml', '[project]\nname = "x"\nversion = "1.0.0"\n')
    _write(repo, 'src/pytest_gremlins/__init__.py', "__version__ = '1.0.0'\n")
    _write(repo, 'CHANGELOG.md', '## v1.0.0 (2026-01-01)\n')
    _commit_all(repo, 'base')
    _git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    _git(repo, 'switch', '-q', '-c', 'feature/sneaky')
    return repo


def _weaken_the_guard_and_bump_the_version(repo: Path) -> None:
    for script in GUARD_FILES:
        _write(repo, f'scripts/{script}', ALWAYS_PASSES)
    _write(repo, 'pyproject.toml', '[project]\nname = "x"\nversion = "1.1.0"\n')
    _write(repo, 'src/pytest_gremlins/__init__.py', "__version__ = '1.1.0'\n")
    _commit_all(repo, 'weaken the guard and bump')


def _run_step(repo: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    runner_temp = tmp_path / 'runner_temp'
    runner_temp.mkdir()
    github_output = tmp_path / 'github_output'
    env = {
        'PATH': os.environ['PATH'],
        'HOME': os.environ.get('HOME', str(tmp_path)),
        'UV_PYTHON': sys.executable,
        'BASE_REF': 'main',
        'HEAD_REF': 'feature/sneaky',
        'GITHUB_WORKSPACE': str(repo),
        'RUNNER_TEMP': str(runner_temp),
        'GITHUB_OUTPUT': str(github_output),
    }
    completed = subprocess.run(
        ['bash', '-c', _run_text()],  # noqa: S607
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, github_output


@pytest.mark.medium
@POSIX_ONLY
@NEEDS_TOOLS
class DescribeGuardStepAgainstAWeakenedPullRequest:
    def it_fails_a_non_release_branch_that_bumps_the_version_even_when_it_weakened_the_guard(
        self, tmp_path: Path
    ) -> None:
        repo = _make_checkout(tmp_path)
        _weaken_the_guard_and_bump_the_version(repo)

        completed, _ = _run_step(repo, tmp_path)

        assert completed.returncode == GUARD_FAILED, completed.stdout + completed.stderr
        assert 'release/v1.1.0' in completed.stdout

    def it_passes_and_publishes_the_outputs_when_the_version_is_unchanged(self, tmp_path: Path) -> None:
        repo = _make_checkout(tmp_path)
        _write(repo, 'README.md', 'docs\n')
        _commit_all(repo, 'docs only')

        completed, github_output = _run_step(repo, tmp_path)

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert github_output.read_text(encoding='utf-8') == 'version_changed=false\nversion=1.0.0\n'

    @pytest.mark.parametrize('missing', GUARD_FILES)
    def it_exits_2_when_a_guard_file_is_missing_at_the_base(self, tmp_path: Path, missing: str) -> None:
        present = tuple(script for script in GUARD_FILES if script != missing)
        repo = _make_checkout(tmp_path, base_has=present)

        completed, _ = _run_step(repo, tmp_path)

        assert completed.returncode == GUARD_COULD_NOT_RUN
        assert f'::error::scripts/{missing} is missing at origin/main' in completed.stdout + completed.stderr
