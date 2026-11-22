"""Adversarial QA (issue #1049, run 2): the guard reads blobs, but the checkout and the build read the working tree.

``check_version_change.py`` now reads ``pyproject.toml`` and ``__init__.py`` as git blobs at ``HEAD``. The build,
``uv sync`` and ``tag-release.yml`` read the files that ``actions/checkout`` wrote to the working tree. Git's built-in
``ident`` attribute needs no config: a ``.gitattributes`` line from the pull request makes checkout rewrite
``$Id: <anything without spaces> $`` to ``$Id: <blob sha> $``. Text inside that marker exists in the blob and is gone
from the working tree, so the two can hold different versions. The blobs are committed before the attribute, so
``git add`` does not collapse the marker.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib

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

INIT = 'src/pytest_gremlins/__init__.py'
FUTURE = '9.9.9'
# The blob reads version 1.0.0 (the rest of the line is a comment); after the ident smudge it reads 9.9.9.
PYPROJECT_BLOB = 'project = {name = "x", description = "$Id: ",version="1.0.0"}# $", version = "9.9.9"}\n'
INIT_BLOB = '_ = "$Id: ";__version__="1.0.0"# $";__version__ = "9.9.9"\n'


def _plant_ident_versions(repo: Path) -> None:
    _write(repo, 'pyproject.toml', PYPROJECT_BLOB)
    _write(repo, INIT, INIT_BLOB)
    _commit_all(repo, 'version files that change under ident')
    _write(repo, '.gitattributes', f'pyproject.toml ident\n{INIT} ident\n')
    _commit_all(repo, 'turn on ident')
    # What actions/checkout does: write the working tree from the commit, applying .gitattributes.
    (repo / 'pyproject.toml').unlink()
    (repo / INIT).unlink()
    _git(repo, 'checkout', 'HEAD', '--', 'pyproject.toml', INIT)


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='the step runs in bash on ubuntu-latest')
@NEEDS_TOOLS
class DescribeGuardStepAgainstIdentExpandedVersionFiles:
    def it_does_not_pass_a_working_tree_version_that_differs_from_the_merge_base(self, tmp_path: Path) -> None:
        repo = _make_checkout(tmp_path)
        _plant_ident_versions(repo)
        shipped = tomllib.loads((repo / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
        assert shipped == FUTURE

        completed, github_output = _run_step(repo, tmp_path)

        assert completed.returncode == GUARD_COULD_NOT_RUN, completed.stdout + completed.stderr
        assert 'differs from the committed blob' in completed.stderr
        assert not github_output.exists()
