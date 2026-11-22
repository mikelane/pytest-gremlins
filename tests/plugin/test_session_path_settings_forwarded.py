"""Relative path settings resolve the same way in gremlin runs as in the session (#1037).

A gremlin run is given ``-c <session config file>``, or the packaged ``no_config.ini`` when the session read none.
Pytest resolves a relative ``paths`` ini value against the directory of that file, so ``-o pythonpath=src`` from
``PYTEST_ADDOPTS`` pointed inside the installed package and no gremlin run could import the project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    SAMPLE,
    verdicts,
)

from pytest_gremlins.plugin import _path_ini_overrides

if TYPE_CHECKING:
    from pathlib import Path

GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=src/sample.py',
    '--gremlin-operators=comparison',
    '-p',
    'no:cacheprovider',
)

TEST_FILE = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""


@pytest.fixture(autouse=True)
def child_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child output UTF-8 and keep coverage's subprocess hook out of the children."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)


@pytest.fixture
def src_layout_project(pytester_with_markers: pytest.Pytester) -> Path:
    """A project whose module lives in ``src/`` and which has no config file."""
    root = pytester_with_markers.path
    (root / 'src').mkdir()
    (root / 'src' / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    (root / 'test_sample.py').write_text(TEST_FILE, encoding='utf-8')
    return root


@pytest.mark.medium
@pytest.mark.usefixtures('src_layout_project')
class DescribeASessionWithNoConfigFileAndARelativePathSettingInAddopts:
    def it_resolves_the_path_setting_in_gremlin_runs_as_the_session_did(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-o pythonpath=src')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '.')

        counts = verdicts(result.stdout.str())
        assert counts['Zapped'] + counts['Survived'] > 0, result.stdout.str()
        assert counts['Error'] == 0, result.stdout.str()


@pytest.mark.medium
@pytest.mark.usefixtures('src_layout_project')
class DescribeASessionWithAConfigFileAndARelativePathSetting:
    def it_resolves_the_path_setting_against_the_config_files_directory(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'pytest.ini').write_text('[pytest]\npythonpath = src\n', encoding='utf-8')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '.')

        counts = verdicts(result.stdout.str())
        assert counts['Zapped'] + counts['Survived'] > 0, result.stdout.str()
        assert counts['Error'] == 0, result.stdout.str()


@pytest.mark.medium
class DescribePathIniOverrides:
    def it_forwards_each_path_in_a_list_setting_as_one_shell_word(self, pytester: pytest.Pytester) -> None:
        config = pytester.parseconfig('-o', 'pythonpath=src "my lib"')

        overrides = _path_ini_overrides(config)

        assert overrides == ['-o', f"pythonpath={pytester.path / 'src'} '{pytester.path / 'my lib'}'"]

    def it_forwards_nothing_when_the_session_read_a_config_file(self, pytester: pytest.Pytester) -> None:
        pytester.makeini('[pytest]\npythonpath = src\n')

        assert _path_ini_overrides(pytester.parseconfig()) == []

    def it_forwards_nothing_when_no_path_setting_is_set(self, pytester: pytest.Pytester) -> None:
        assert _path_ini_overrides(pytester.parseconfig()) == []
