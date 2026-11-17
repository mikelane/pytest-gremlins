"""Gremlin runs and the coverage pre-scan read the config the session read, not one pytest finds below it (#1023).

The session runs on ``.`` and child sessions run on node ids such as ``pkg1/test_x.py::test_big`` from the rootdir.
Pytest starts looking for a config file at the common ancestor of the arguments, so with only a nested
``pkg1/pytest.ini`` the session read no config file while every child read ``pkg1/pytest.ini``: its rerun count,
its ``xfail_strict``, and a ``confcutdir`` of ``pkg1`` that kept the child from loading the root ``conftest.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    SAMPLE,
    verdicts,
)

if TYPE_CHECKING:
    from pathlib import Path

ROOT_FIXTURE = """

@pytest.fixture
def root_value():
    return 42
"""

GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

NESTED_INI = '[pytest]\nreruns = 3\nxfail_strict = true\n'

RECORDING_TEST = """
import json
import os
from pathlib import Path

from sample import classify


def test_big(root_value, request):
    record = {
        'gremlin_run': 'ACTIVE_GREMLIN' in os.environ,
        'rootpath': request.config.rootpath.as_posix(),
        'reruns': request.config.getini('reruns'),
        'xfail_strict': bool(request.config.getini('xfail_strict')),
    }
    with (Path(__file__).parent.parent / 'records.jsonl').open('a', encoding='utf-8') as records:
        records.write(json.dumps(record) + '\\n')
    assert root_value == 42
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""


@pytest.fixture(autouse=True)
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest processes write UTF-8 so the parent decodes their output on any platform."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.fixture
def nested_config_project(pytester_with_markers: pytest.Pytester) -> Path:
    """A project whose only config file is ``pkg1/pytest.ini`` and whose root ``conftest.py`` holds a fixture."""
    root = pytester_with_markers.path
    conftest = root / 'conftest.py'
    conftest.write_text(conftest.read_text(encoding='utf-8') + ROOT_FIXTURE, encoding='utf-8')
    (root / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    (root / 'pkg1').mkdir()
    (root / 'pkg1' / 'pytest.ini').write_text(NESTED_INI, encoding='utf-8')
    (root / 'pkg1' / 'test_x.py').write_text(RECORDING_TEST, encoding='utf-8')
    return root


def _records(root: Path) -> list[dict[str, object]]:
    lines = (root / 'records.jsonl').read_text(encoding='utf-8').splitlines()
    return [json.loads(line) for line in lines]


def _scored_gremlins(result: pytest.RunResult) -> int:
    """Return how many gremlins were run: with no reruns, each runs the covering test exactly once."""
    counts: dict[str, int] = verdicts(result.stdout.str())
    return counts['Zapped'] + counts['Survived']


def _settings(record: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key != 'gremlin_run'}


@pytest.mark.medium
class DescribeASessionWhoseOnlyConfigFileIsNested:
    def it_gives_every_gremlin_run_the_settings_the_session_ran_with(
        self, pytester_with_markers: pytest.Pytester, nested_config_project: Path
    ) -> None:
        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '.')

        records = _records(nested_config_project)
        baseline = _settings(records[0])
        gremlin_runs = [record for record in records if record['gremlin_run']]
        assert baseline == {
            'rootpath': nested_config_project.as_posix(),
            'reruns': '',
            'xfail_strict': False,
        }
        assert [_settings(record) for record in records] == [baseline] * len(records), records
        assert _scored_gremlins(result) > 0, result.stdout.str()
        assert len(gremlin_runs) == _scored_gremlins(result), result.stdout.str()


@pytest.mark.medium
class DescribeASessionWithAConfigFileAboveANestedOne:
    def it_gives_every_gremlin_run_the_config_file_the_session_read(
        self, pytester_with_markers: pytest.Pytester, nested_config_project: Path
    ) -> None:
        (nested_config_project / 'pytest.ini').write_text('[pytest]\nreruns = 0\n', encoding='utf-8')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '.')

        records = _records(nested_config_project)
        baseline = _settings(records[0])
        gremlin_runs = [record for record in records if record['gremlin_run']]
        assert baseline == {
            'rootpath': nested_config_project.as_posix(),
            'reruns': '0',
            'xfail_strict': False,
        }
        assert [_settings(record) for record in records] == [baseline] * len(records), records
        assert _scored_gremlins(result) > 0, result.stdout.str()
        assert len(gremlin_runs) == _scored_gremlins(result), result.stdout.str()
