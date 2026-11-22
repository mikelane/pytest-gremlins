"""Adversarial QA (issue #1049): a stacked pull request's base is the layer below it, which its author controls.

GitHub native stacks run ``pull_request`` CI for an upper layer whose base is the lower layer's branch (seen on #855,
whose run on 2026-10-27 merged into d509da5, the tip of #775's head branch, not main). A guard step that exported its
copy from ``origin/$BASE_REF`` would check the upper layer with the lower layer's guard. A lower layer that weakens the
guard passes main's guard (it does not bump the version), and an upper layer that bumps the version then passes the
weakened copy. A whole-stack async merge lands both on main with every check green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.test_ci_release_pr_guard_from_default_branch import (
    ALWAYS_PASSES,
    GUARD_FAILED,
    NEEDS_TOOLS,
    POSIX_ONLY,
    _commit_all,
    _git,
    _make_checkout,
    _run_step,
    _write,
)


def _stack_with_a_weakened_lower_layer(tmp_path: Path) -> Path:
    repo = _make_checkout(tmp_path)
    _git(repo, 'switch', '-q', '-c', 'lower-layer', 'main')
    _write(repo, 'scripts/check_version_change.py', ALWAYS_PASSES)
    _commit_all(repo, 'lower layer weakens the guard')
    _git(repo, 'update-ref', 'refs/remotes/origin/lower-layer', 'HEAD')
    _git(repo, 'switch', '-q', '-c', 'upper-layer')
    _write(repo, 'pyproject.toml', '[project]\nname = "x"\nversion = "9.9.9"\n')
    _write(repo, 'src/pytest_gremlins/__init__.py', "__version__ = '9.9.9'\n")
    _commit_all(repo, 'upper layer bumps the version')
    return repo


@pytest.mark.medium
@POSIX_ONLY
@NEEDS_TOOLS
class DescribeGuardStepOnAStackedPullRequest:
    def it_fails_an_upper_layer_that_bumps_the_version_over_a_lower_layer_that_weakened_the_guard(
        self, tmp_path: Path
    ) -> None:
        repo = _stack_with_a_weakened_lower_layer(tmp_path)
        completed, _ = _run_step(repo, tmp_path, extra_env={'BASE_REF': 'lower-layer', 'HEAD_REF': 'upper-layer'})

        assert completed.returncode == GUARD_FAILED, completed.stdout + completed.stderr
        assert 'release/v9.9.9' in completed.stdout
