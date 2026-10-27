"""Tests for the repo's hermeticity gate, which makes strict enforcement fail the build.

pytest-test-categories records a violation when a test spawns a process, but if the code under test
swallows the resulting exception the test still passes and pytest exits 0 (#474).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SWALLOWED_SUBPROCESS_TEST = """
import subprocess

import pytest


@pytest.mark.small
def test_swallows_the_violation():
    try:
        subprocess.run(['python', '-c', 'pass'], check=False)
    except Exception:
        pass


@pytest.mark.small
def test_is_hermetic():
    assert 1 + 1 == 2
"""


SLOW_PROCESS_SHIM = """#!/bin/sh
sleep 1.5
exec "$REAL_PYTHON" "$@"
"""

SWALLOWED_FILESYSTEM_READ_TEST = """
import pytest


@pytest.mark.small
def test_reads_the_filesystem():
    try:
        open(__file__).close()
    except Exception:
        pass
"""


SWALLOWED_THEN_SKIPPED_TEST = """
import subprocess

import pytest


@pytest.mark.small
def test_swallows_then_skips():
    try:
        subprocess.run(['python', '-c', 'pass'], check=False)
    except Exception:
        pass
    pytest.skip('environment not ready')
"""

SWALLOWED_NON_STRICT_XPASS_TEST = """
import subprocess

import pytest


@pytest.mark.small
@pytest.mark.xfail(reason='known')
def test_swallows_and_xpasses():
    try:
        subprocess.run(['python', '-c', 'pass'], check=False)
    except Exception:
        pass
"""


@pytest.fixture
def violating_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
    pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
    pytester.makepyfile(test_sample=SWALLOWED_SUBPROCESS_TEST)
    return pytester


@pytest.mark.medium
class DescribeHermeticityGate:
    def it_leaves_exit_status_zero_without_the_gate(self, violating_project: pytest.Pytester) -> None:
        """Canary for the upstream bug: skips itself once pytest-test-categories fixes #267."""
        result = violating_project.runpytest_subprocess('-p', 'no:cacheprovider')

        if result.ret != 0:
            pytest.skip('pytest-test-categories now fails swallowed violations; remove hermeticity_gate.py')
        assert result.ret == 0

    def it_fails_the_violating_test_with_the_gate(self, violating_project: pytest.Pytester) -> None:
        result = violating_project.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'hermeticity_gate')

        assert result.ret != 0
        result.assert_outcomes(passed=1, failed=1)

    def it_fails_the_violating_test_under_xdist(self, violating_project: pytest.Pytester) -> None:
        result = violating_project.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'hermeticity_gate', '-n', '2')

        assert result.ret != 0
        result.assert_outcomes(passed=1, failed=1)

    def it_leaves_clean_suites_green(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
        pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
        pytester.makepyfile(test_clean='import pytest\n\n@pytest.mark.small\ndef test_ok():\n    assert True\n')

        result = pytester.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'hermeticity_gate')

        assert result.ret == 0

    def it_leaves_warn_mode_violations_as_warnings(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
        pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
        pytester.makepyfile(test_sample=SWALLOWED_FILESYSTEM_READ_TEST)

        result = pytester.runpytest_subprocess(
            '-p', 'no:cacheprovider', '-p', 'hermeticity_gate', '--test-categories-enforcement=warn'
        )

        assert result.ret == 0

    def it_keeps_warn_mode_green_when_spawned_processes_are_slow(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
        pytester.makepyfile(test_sample=SWALLOWED_FILESYSTEM_READ_TEST)
        monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
        shim = tmp_path / 'python'
        shim.write_text(SLOW_PROCESS_SHIM, encoding='utf-8')
        shim.chmod(0o755)
        monkeypatch.setenv('REAL_PYTHON', sys.executable)
        monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')

        result = pytester.runpytest_subprocess(
            '-p', 'no:cacheprovider', '-p', 'hermeticity_gate', '--test-categories-enforcement=warn'
        )

        assert result.ret == 0

    def it_fails_a_test_that_swallows_a_violation_then_skips(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
        pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
        pytester.makepyfile(test_sample=SWALLOWED_THEN_SKIPPED_TEST)

        result = pytester.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'hermeticity_gate')

        assert result.ret != 0

    def it_fails_a_non_strict_xpass_that_swallows_a_violation(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
        pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
        pytester.makepyfile(test_sample=SWALLOWED_NON_STRICT_XPASS_TEST)

        result = pytester.runpytest_subprocess('-p', 'no:cacheprovider', '-p', 'hermeticity_gate')

        assert result.ret != 0


@pytest.mark.medium
def it_ships_the_gate_module_in_the_sdist_alongside_its_tests() -> None:
    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))

    sdist_includes = pyproject['tool']['hatch']['build']['targets']['sdist']['include']

    assert '/hermeticity_gate.py' in sdist_includes
