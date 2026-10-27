"""Tests for the repo's hermeticity gate, which makes strict enforcement fail the build.

pytest-test-categories records a violation when a test spawns a process, but if the code under test
swallows the resulting exception the test still passes and pytest exits 0 (#474).
"""

from __future__ import annotations

from pathlib import Path

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


@pytest.fixture
def violating_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv('PYTHONPATH', str(REPO_ROOT))
    pytester.makeini('[pytest]\ntest_categories_enforcement = strict\nmarkers = small: fast\n')
    pytester.makepyfile(test_sample=SWALLOWED_SUBPROCESS_TEST)
    return pytester


@pytest.mark.medium
class DescribeHermeticityGate:
    def it_leaves_exit_status_zero_without_the_gate(self, violating_project: pytest.Pytester) -> None:
        result = violating_project.runpytest_subprocess('-p', 'no:cacheprovider')

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

    def it_leaves_warn_mode_violations_as_warnings(self, violating_project: pytest.Pytester) -> None:
        result = violating_project.runpytest_subprocess(
            '-p', 'no:cacheprovider', '-p', 'hermeticity_gate', '--test-categories-enforcement=warn'
        )

        assert result.ret == 0
