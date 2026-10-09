"""The release-step execution tests run bash and POSIX venv paths (.venv/bin/python), so they must skip on Windows.

CI (ci.yml and release.yml's ``test`` job) runs ``-m "small or medium"`` on windows-latest. There ``uv venv``
creates ``.venv\\Scripts\\python.exe``, the subprocess env drops SYSTEMROOT, and PATH is joined with ':' after a
drive-letter path, so these tests cannot pass. This check fakes ``sys.platform == 'win32'`` while the test modules
are imported and
asserts the bash-executing tests are skipped rather than run.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_TESTS = Path(__file__).resolve().parent
FAKE_WINDOWS_PLUGIN = """
import sys

import pytest


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    if not isinstance(collector, pytest.Module):
        return (yield)
    real_platform, sys.platform = sys.platform, 'win32'
    try:
        return (yield)
    finally:
        sys.platform = real_platform
"""
BASH_EXECUTING_TESTS = (
    'test_release_workflow_install_step.py::DescribeVerifyTestPypiInstall::'
    'it_installs_the_new_release_from_test_pypi_when_pypi_only_has_older_versions',
    'test_release_workflow.py::DescribeReleaseWorkflowInstallChecks::'
    'it_exits_non_zero_when_the_test_pypi_version_differs_from_the_release_tag',
    'test_release_workflow.py::DescribeReleaseWorkflowTagVerification::'
    'it_exits_non_zero_for_a_dispatch_that_is_not_from_main',
)


@pytest.mark.medium
class DescribePosixOnlyReleaseStepTests:
    @pytest.mark.parametrize('node_id', BASH_EXECUTING_TESTS)
    def it_skips_bash_executing_release_step_tests_on_windows(self, tmp_path: Path, node_id: str) -> None:
        (tmp_path / 'fake_windows.py').write_text(FAKE_WINDOWS_PLUGIN)

        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'pytest',
                '-p',
                'fake_windows',
                '-p',
                'no:randomly',
                '-q',
                '-rs',
                str(SCRIPTS_TESTS / node_id),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=SCRIPTS_TESTS.parents[1],
            env={**os.environ, 'PYTHONPATH': str(tmp_path)},
        )

        assert '1 skipped' in result.stdout, result.stdout
