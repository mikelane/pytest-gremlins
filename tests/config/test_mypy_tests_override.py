"""The ``[[tool.mypy.overrides]]`` block for ``tests.*`` must match real module names (issue #478).

Without ``explicit_package_bases``, mypy names test modules after their subpackage (``plugin.test_x``), so the
override never matched and mypy reported ``unused section(s): module = ['tests.*']``.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_mypy_on_test_module() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', 'mypy', '--no-incremental', 'tests/config/test_ruff_floor.py'],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def assert_mypy_checked_without_unused_override(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert 'Success: no issues found' in result.stdout, output
    assert 'unused section' not in output, output


@pytest.mark.small
class DescribeMypyGuardAssertion:
    def it_rejects_a_mypy_that_exited_fatally_without_checking(self) -> None:
        fatal = subprocess.CompletedProcess(args=['mypy'], returncode=2, stdout='', stderr='fatal error')

        with pytest.raises(AssertionError):
            assert_mypy_checked_without_unused_override(fatal)

    def it_rejects_an_unused_section_warning_even_on_success(self) -> None:
        warned = subprocess.CompletedProcess(
            args=['mypy'],
            returncode=0,
            stdout='Success: no issues found in 1 source file',
            stderr="unused section(s) in pyproject.toml: module = ['tests.*']",
        )

        with pytest.raises(AssertionError):
            assert_mypy_checked_without_unused_override(warned)


@pytest.mark.medium
class DescribeMypyTestsOverride:
    def it_is_applied_to_test_modules_instead_of_reported_unused(self) -> None:
        assert_mypy_checked_without_unused_override(run_mypy_on_test_module())
