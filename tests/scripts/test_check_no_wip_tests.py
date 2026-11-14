"""Tests for scripts/check_no_wip_tests.py -- the release gate that refuses to ship unfinished (``wip``) scenarios."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_no_wip_tests.py'

WIP_TEST = """
import pytest

@pytest.mark.wip
def test_unfinished_feature():
    assert False
"""
FINISHED_TEST = """
def test_finished_feature():
    assert True
"""
GHERKIN_FEATURE = """
Feature: Unfinished feature

  @wip
  Scenario: Not done yet
    Given a thing
"""
GHERKIN_STEPS = """
from pytest_bdd import given, scenarios

scenarios('unfinished.feature')

@given('a thing')
def _thing():
    return None
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_no_wip_tests', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _run_script(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--repo', str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeCheckNoWipTests:
    def it_exits_zero_when_no_test_is_marked_wip(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_finished.py', FINISHED_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr

    def it_exits_zero_when_there_are_no_tests_at_all(self, tmp_path: Path) -> None:
        result = _run_script(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr

    def it_exits_one_and_lists_the_wip_test_id(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_unfinished.py', WIP_TEST)
        _write(tmp_path, 'tests/test_finished.py', FINISHED_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'tests/test_unfinished.py::test_unfinished_feature' in result.stdout
        assert 'test_finished_feature' not in result.stdout

    def it_lists_every_wip_test(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_one.py', WIP_TEST)
        _write(tmp_path, 'tests/test_two.py', WIP_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'tests/test_one.py::test_unfinished_feature' in result.stdout
        assert 'tests/test_two.py::test_unfinished_feature' in result.stdout

    def it_exits_two_when_collection_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_broken.py', 'def test_broken(:\n')

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert result.stderr.strip() != ''

    def it_catches_a_gherkin_scenario_tagged_wip(self, tmp_path: Path) -> None:
        pytest.importorskip('pytest_bdd')
        _write(tmp_path, 'tests/unfinished.feature', GHERKIN_FEATURE)
        _write(tmp_path, 'tests/test_unfinished.py', GHERKIN_STEPS)

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'test_not_done_yet' in result.stdout


@pytest.mark.small
class DescribeParseCollectedIds:
    def it_keeps_only_test_id_lines(self) -> None:
        script = _load_script()
        output = 'tests/a.py::test_x\ntests/b.py::DescribeY::it_z\n\n2/9 tests collected (7 deselected) in 0.01s\n'

        assert script.parse_collected_ids(output) == ['tests/a.py::test_x', 'tests/b.py::DescribeY::it_z']

    def it_ignores_a_warning_line_that_quotes_a_test_id(self) -> None:
        script = _load_script()
        output = '/venv/plugin.py:171: PytestWarning: Test has no size marker: tests/a.py::test_x\ntests/a.py::test_y\n'

        assert script.parse_collected_ids(output) == ['tests/a.py::test_y']
