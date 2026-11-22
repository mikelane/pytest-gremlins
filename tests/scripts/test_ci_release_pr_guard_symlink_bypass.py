"""Adversarial QA (issue #1049): the version guard reads HEAD through symlinks but the merge base as raw blobs.

``check_version_change.py`` reads ``pyproject.toml`` and ``__init__.py`` at ``HEAD`` from the working tree, which
follows a symlink to its target, and at the merge base with ``git show <sha>:<path>``, which prints a symlink's link
text. An earlier pull request that leaves the version unchanged can turn both files into symlinks whose link text is
itself valid TOML / Python naming a future version, pointing at files that still hold the current version. A later
pull request from any branch then bumps the real version by editing only the targets: the guard reads the merge-base
link text as the new version, reports the version as unchanged and passes, so the release gates never run.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from tests.scripts.test_ci_release_pr_guard_from_base import (
    GUARD_COULD_NOT_RUN,
    NEEDS_TOOLS,
    _commit_all,
    _git,
    _make_checkout,
    _run_step,
    _write,
)

FUTURE = '9.9.9'
PYPROJECT_LINK = f'project.version="{FUTURE}"'
INIT_LINK = f"__version__ = '{FUTURE}'"


def _plant_symlinks_that_keep_the_version(repo: Path) -> None:
    """The earlier pull request: same effective version 1.0.0, but the link texts name the future version."""
    _write(repo, PYPROJECT_LINK, '[project]\nname = "x"\nversion = "1.0.0"\n')
    (repo / 'pyproject.toml').unlink()
    (repo / 'pyproject.toml').symlink_to(PYPROJECT_LINK)
    _write(repo, f'src/pytest_gremlins/{INIT_LINK}', "__version__ = '1.0.0'\n")
    (repo / 'src/pytest_gremlins/__init__.py').unlink()
    (repo / 'src/pytest_gremlins/__init__.py').symlink_to(INIT_LINK)
    _commit_all(repo, 'symlink the version files')


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='needs symlinks')
@NEEDS_TOOLS
class DescribeGuardStepAgainstThePlantingPullRequest:
    def it_refuses_the_pull_request_that_plants_the_symlinks(self, tmp_path: Path) -> None:
        repo = _make_checkout(tmp_path)
        _plant_symlinks_that_keep_the_version(repo)

        completed, _ = _run_step(repo, tmp_path)

        assert completed.returncode == GUARD_COULD_NOT_RUN, completed.stdout + completed.stderr
        assert 'git mode 120000' in completed.stderr


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='needs symlinks')
@NEEDS_TOOLS
class DescribeGuardStepAgainstSymlinkedVersionFiles:
    def it_fails_a_non_release_branch_that_bumps_the_version_through_symlink_targets(self, tmp_path: Path) -> None:
        repo = _make_checkout(tmp_path)
        _git(repo, 'switch', '-q', 'main')
        _plant_symlinks_that_keep_the_version(repo)
        _git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        _git(repo, 'switch', '-q', '-C', 'feature/sneaky')
        _write(repo, PYPROJECT_LINK, f'[project]\nname = "x"\nversion = "{FUTURE}"\n')
        _write(repo, f'src/pytest_gremlins/{INIT_LINK}', f"__version__ = '{FUTURE}'\n")
        _write(repo, 'scripts/anything.py', 'print("not a release file")\n')
        _commit_all(repo, 'bump the version through the symlink targets')

        completed, _ = _run_step(repo, tmp_path)

        assert completed.returncode == GUARD_COULD_NOT_RUN, completed.stdout + completed.stderr
        assert 'is not a regular file' in completed.stderr
