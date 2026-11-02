"""The sharded coverage pre-scan records what the serial one records, or abstains (issue #527)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.coverage.sharded_prescan import run_sharded_prescan
from pytest_gremlins.plugin import (
    GremlinSession,
    _run_prescan_reporting_problems,
    _run_tests_with_coverage,
)

_TARGET = """\
def classify(code):
    if code < 400:
        return 'ok'
    return 'err'


def double(value):
    return value * 2


def label(name):
    return name.upper()


async def fetch(code):
    if code < 400:
        return 'ok'
    return 'err'
"""

_CONFTEST = """\
import asyncio
import inspect

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**arguments))
        return True
    return None
"""

_TEST_PLAIN = """\
from sample import classify, double


def test_classify_ok():
    assert classify(200) == 'ok'


def test_classify_err():
    assert classify(500) == 'err'


def test_double():
    assert double(2) == 4
"""

_TEST_PARAMETRIZED = """\
import pytest
from sample import double, label


@pytest.mark.parametrize('value', [1, 2, 3])
def test_double_param(value):
    assert double(value) == value * 2


@pytest.mark.parametrize('name', ['a', 'b'])
def test_label_param(name):
    assert label(name) == name.upper()
"""

_TEST_ASYNC = """\
from sample import fetch


async def test_fetch_ok():
    assert await fetch(200) == 'ok'


async def test_fetch_err():
    assert await fetch(500) == 'err'
"""

_SERIAL_NODE_IDS = [
    'test_plain.py::test_classify_ok',
    'test_plain.py::test_classify_err',
    'test_plain.py::test_double',
    'test_parametrized.py::test_double_param[1]',
    'test_parametrized.py::test_double_param[2]',
    'test_parametrized.py::test_double_param[3]',
    'test_parametrized.py::test_label_param[a]',
    'test_parametrized.py::test_label_param[b]',
    'test_async.py::test_fetch_ok',
    'test_async.py::test_fetch_err',
]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    (tmp_path / 'sample.py').write_text(_TARGET, encoding='utf-8')
    (tmp_path / 'conftest.py').write_text(_CONFTEST, encoding='utf-8')
    (tmp_path / 'test_plain.py').write_text(_TEST_PLAIN, encoding='utf-8')
    (tmp_path / 'test_parametrized.py').write_text(_TEST_PARAMETRIZED, encoding='utf-8')
    (tmp_path / 'test_async.py').write_text(_TEST_ASYNC, encoding='utf-8')
    return tmp_path


def _mapping(project: Path, workers: int, *, preserved_addopts: str = '') -> set[tuple[str, int, str]]:
    coverage_data = _run_tests_with_coverage(
        _SERIAL_NODE_IDS,
        project,
        coverage_include=[str((project / 'sample.py').resolve())],
        preserved_addopts=preserved_addopts,
        prescan_workers=workers,
    )
    return {
        (file, line, node_id)
        for node_id, files in coverage_data.items()
        for file, lines in files.items()
        for line in lines
    }


@pytest.mark.medium
class DescribeParallelPrescanEquivalence:
    def it_records_every_node_id_including_parametrized_and_async_ones_when_serial(self, project: Path) -> None:
        recorded = {node_id for _file, _line, node_id in _mapping(project, 1)}

        assert recorded == set(_SERIAL_NODE_IDS)

    @pytest.mark.parametrize('workers', [2, 3])
    def it_records_the_same_file_line_and_node_id_triples_as_the_serial_pre_scan(
        self, project: Path, workers: int
    ) -> None:
        serial = _mapping(project, 1)

        assert _mapping(project, workers) == serial

    def it_records_the_same_triples_when_there_are_more_workers_than_files(self, project: Path) -> None:
        assert _mapping(project, 8) == _mapping(project, 1)

    def it_records_the_same_triples_when_the_project_runs_its_own_tests_under_xdist(self, project: Path) -> None:
        assert _mapping(project, 2, preserved_addopts='-n 2') == _mapping(project, 1)

    def it_leaves_no_coverage_files_behind(self, project: Path) -> None:
        _mapping(project, 2)

        assert not (project / '.coverage').exists()
        assert not (project / '.coveragerc.gremlins').exists()


@pytest.mark.medium
class DescribeWhenTheShardedPathRuns:
    def it_shards_only_when_more_than_one_worker_is_asked_for(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def spy(*args: Any, **kwargs: Any) -> bool:
            calls.append(kwargs['worker_count'])
            return run_sharded_prescan(*args, **kwargs)

        monkeypatch.setattr(plugin, 'run_sharded_prescan', spy)

        _mapping(project, 1)
        _mapping(project, 3)

        assert calls == [3]


@pytest.mark.medium
class DescribeParallelPrescanAbstains:
    def it_returns_no_data_and_the_existing_notice_when_one_shard_cannot_collect(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / 'test_async.py').write_text('def test_fetch_ok(:\n', encoding='utf-8')

        coverage_data = _run_prescan_reporting_problems(
            _SERIAL_NODE_IDS,
            project,
            GremlinSession(prescan_workers=3),
            coverage_include=[str((project / 'sample.py').resolve())],
        )

        assert coverage_data == {}
        assert 'Coverage collection returned no data' in capsys.readouterr().err

    def it_returns_no_data_and_the_timeout_notice_when_a_shard_outlasts_the_limit(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / 'test_async.py').write_text(
            'import time\n\n\ndef test_fetch_ok():\n    time.sleep(60)\n\n\ndef test_fetch_err():\n    pass\n',
            encoding='utf-8',
        )

        coverage_data = _run_prescan_reporting_problems(
            _SERIAL_NODE_IDS,
            project,
            GremlinSession(prescan_workers=3, coverage_timeout=3),
            coverage_include=[str((project / 'sample.py').resolve())],
        )

        assert coverage_data == {}
        assert 'coverage pre-scan exceeded 3s' in capsys.readouterr().err


@pytest.mark.medium
class DescribeParallelPrescanInARealRun:
    def it_narrows_each_gremlin_to_its_covering_tests_with_two_pre_scan_workers(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester_with_markers.makepyfile(
            target='def add(a, b):\n    return a + b\n\n\ndef twice(a):\n    return a * 2\n',
            test_one='from target import add\n\n\ndef test_one():\n    assert add(1, 2) == 3\n',
            test_two='from target import twice\n\n\ndef test_two():\n    assert twice(2) == 4\n',
        )

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', '--gremlin-prescan-workers=2'
        )

        result.stdout.fnmatch_lines(['*running 1/2 tests*'])
        assert 'running 2/2 tests' not in result.stdout.str()
        assert 'coverage-guided test selection disabled' not in result.stderr.str()
        assert 'Coverage collection returned no data' not in result.stderr.str()
