"""The sharded coverage pre-scan records what the serial one records, or abstains (issue #527)."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
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

_PLAIN_NODE_IDS = _SERIAL_NODE_IDS[:3]

_PLAIN_TRIPLES = {
    ('sample.py', 2, 'test_plain.py::test_classify_ok'),
    ('sample.py', 3, 'test_plain.py::test_classify_ok'),
    ('sample.py', 2, 'test_plain.py::test_classify_err'),
    ('sample.py', 4, 'test_plain.py::test_classify_err'),
    ('sample.py', 8, 'test_plain.py::test_double'),
}

_EXPECTED_TRIPLES = {
    *_PLAIN_TRIPLES,
    ('sample.py', 8, 'test_parametrized.py::test_double_param[1]'),
    ('sample.py', 8, 'test_parametrized.py::test_double_param[2]'),
    ('sample.py', 8, 'test_parametrized.py::test_double_param[3]'),
    ('sample.py', 12, 'test_parametrized.py::test_label_param[a]'),
    ('sample.py', 12, 'test_parametrized.py::test_label_param[b]'),
    ('sample.py', 16, 'test_async.py::test_fetch_ok'),
    ('sample.py', 17, 'test_async.py::test_fetch_ok'),
    ('sample.py', 16, 'test_async.py::test_fetch_err'),
    ('sample.py', 18, 'test_async.py::test_fetch_err'),
}


_SOCKET_TEST = """\
import socket

from sample import double


def test_sock(tmp_path):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(tmp_path / 's'))
    server.close()
    assert double(1) == 2
"""

_OTHER_TEST = """\
from sample import double


def test_other():
    assert double(2) == 4
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    (tmp_path / 'sample.py').write_text(_TARGET, encoding='utf-8')
    (tmp_path / 'conftest.py').write_text(_CONFTEST, encoding='utf-8')
    (tmp_path / 'test_plain.py').write_text(_TEST_PLAIN, encoding='utf-8')
    (tmp_path / 'test_parametrized.py').write_text(_TEST_PARAMETRIZED, encoding='utf-8')
    (tmp_path / 'test_async.py').write_text(_TEST_ASYNC, encoding='utf-8')
    return tmp_path


def _mapping(
    project: Path, workers: int, *, preserved_addopts: str = '', node_ids: list[str] | None = None
) -> set[tuple[str, int, str]]:
    coverage_data = _run_tests_with_coverage(
        _SERIAL_NODE_IDS if node_ids is None else node_ids,
        project,
        coverage_include=[str((project / 'sample.py').resolve())],
        preserved_addopts=preserved_addopts,
        prescan_workers=workers,
    )
    return {
        (Path(file).name, line, node_id)
        for node_id, files in coverage_data.items()
        for file, lines in files.items()
        for line in lines
    }


@pytest.mark.medium
class DescribeParallelPrescanEquivalence:
    def it_records_every_node_id_including_parametrized_and_async_ones_when_serial(self, project: Path) -> None:
        recorded = {node_id for _file, _line, node_id in _mapping(project, 1)}

        assert recorded == set(_SERIAL_NODE_IDS)

    def it_records_the_expected_line_level_triples_when_serial(self, project: Path) -> None:
        assert _mapping(project, 1) == _EXPECTED_TRIPLES

    @pytest.mark.parametrize('workers', [2, 3])
    def it_records_the_same_file_line_and_node_id_triples_as_the_serial_pre_scan(
        self, project: Path, workers: int
    ) -> None:
        assert _mapping(project, workers) == _EXPECTED_TRIPLES

    def it_records_the_same_triples_when_there_are_more_workers_than_files(self, project: Path) -> None:
        assert _mapping(project, 8) == _EXPECTED_TRIPLES

    def it_records_the_same_triples_for_a_single_test_file_with_several_workers(self, project: Path) -> None:
        assert _mapping(project, 4, node_ids=_PLAIN_NODE_IDS) == _PLAIN_TRIPLES

    def it_records_the_same_triples_when_the_project_runs_its_own_tests_under_xdist(self, project: Path) -> None:
        assert _mapping(project, 2, preserved_addopts='-n 2') == _EXPECTED_TRIPLES

    def it_keeps_a_test_that_binds_a_unix_socket_in_tmp_path_the_serial_pre_scan_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Where AF_UNIX paths are capped (104 bytes on macOS), a long shard ``tmp_path`` would drop this test."""
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        (tmp_path / 'sample.py').write_text('def double(value):\n    return value * 2\n', encoding='utf-8')
        (tmp_path / 'test_sock.py').write_text(_SOCKET_TEST, encoding='utf-8')
        (tmp_path / 'test_other.py').write_text(_OTHER_TEST, encoding='utf-8')
        node_ids = ['test_sock.py::test_sock', 'test_other.py::test_other']

        def recorded(workers: int) -> set[str]:
            return set(
                _run_tests_with_coverage(
                    node_ids,
                    tmp_path,
                    coverage_include=[str((tmp_path / 'sample.py').resolve())],
                    prescan_workers=workers,
                )
            )

        serial = recorded(1)
        assert 'test_sock.py::test_sock' in serial
        assert recorded(2) >= serial

    @pytest.mark.skipif(sys.platform == 'win32', reason='needs a short /tmp path')
    def it_keeps_a_socket_test_that_fits_under_the_users_short_basetemp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A user ``--basetemp`` keeps ``tmp_path`` short in the serial pre-scan, so it must in a shard too."""
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        short_root = Path(tempfile.mkdtemp(prefix='q', dir='/tmp'))
        try:
            node_ids = self._write_socket_project(tmp_path)

            def recorded(workers: int) -> set[str]:
                return set(
                    _run_tests_with_coverage(
                        node_ids,
                        tmp_path,
                        coverage_include=[str((tmp_path / 'sample.py').resolve())],
                        preserved_addopts=f'--basetemp={(short_root / "bt").as_posix()}',
                        session_basetemp=short_root / 'bt',
                        prescan_workers=workers,
                    )
                )

            serial = recorded(1)
            assert 'test_sock.py::test_sock' in serial
            assert recorded(2) >= serial
        finally:
            shutil.rmtree(short_root, ignore_errors=True)

    @pytest.mark.skipif(sys.platform == 'win32', reason='needs a short /tmp path')
    def it_keeps_a_socket_test_that_fits_under_pytest_debug_temproot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        short_root = Path(tempfile.mkdtemp(prefix='q', dir='/tmp'))
        monkeypatch.setenv('PYTEST_DEBUG_TEMPROOT', str(short_root))
        try:
            node_ids = self._write_socket_project(tmp_path)

            def recorded(workers: int) -> set[str]:
                return set(
                    _run_tests_with_coverage(
                        node_ids,
                        tmp_path,
                        coverage_include=[str((tmp_path / 'sample.py').resolve())],
                        prescan_workers=workers,
                    )
                )

            serial = recorded(1)
            assert 'test_sock.py::test_sock' in serial
            assert recorded(2) >= serial
        finally:
            shutil.rmtree(short_root, ignore_errors=True)

    @staticmethod
    def _write_socket_project(directory: Path) -> list[str]:
        (directory / 'sample.py').write_text('def double(value):\n    return value * 2\n', encoding='utf-8')
        (directory / 'test_sock.py').write_text(_SOCKET_TEST, encoding='utf-8')
        (directory / 'test_other.py').write_text(_OTHER_TEST, encoding='utf-8')
        return ['test_sock.py::test_sock', 'test_other.py::test_other']

    def it_leaves_no_coverage_files_behind(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        scratch_root = tmp_path_factory.mktemp('scratch_root')
        monkeypatch.setattr(tempfile, 'tempdir', str(scratch_root))

        _mapping(project, 2)

        assert list(project.glob('.coverage*')) == []
        assert list(scratch_root.glob('pgs*')) == []


@pytest.fixture
def sharded_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def spy(*args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs['worker_count'])
        return run_sharded_prescan(*args, **kwargs)

    monkeypatch.setattr(plugin, 'run_sharded_prescan', spy)
    return calls


@pytest.mark.medium
class DescribeWhenTheShardedPathRuns:
    def it_shards_only_when_more_than_one_worker_is_asked_for(self, project: Path, sharded_calls: list[int]) -> None:
        calls = sharded_calls
        _mapping(project, 1)
        _mapping(project, 3)

        assert calls == [3]

    def it_reports_an_operating_system_error_as_a_launch_failure_and_removes_its_config(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def cannot_start(*_args: Any, **_kwargs: Any) -> bool:
            raise OSError('cannot start a shard')

        monkeypatch.setattr(plugin, 'run_sharded_prescan', cannot_start)

        with pytest.raises(plugin.CoveragePrescanLaunchError):
            _mapping(project, 2)

        assert list(project.glob('.coverage*')) == []


@pytest.mark.medium
class DescribeParallelPrescanAbstains:
    def it_returns_no_data_and_the_existing_notice_when_one_shard_cannot_collect(
        self, project: Path, capsys: pytest.CaptureFixture[str], sharded_calls: list[int]
    ) -> None:
        (project / 'test_async.py').write_text('def test_fetch_ok(:\n', encoding='utf-8')

        coverage_data = _run_prescan_reporting_problems(
            _SERIAL_NODE_IDS,
            project,
            GremlinSession(prescan_workers=3),
            coverage_include=[str((project / 'sample.py').resolve())],
        )

        assert sharded_calls == [3]
        assert coverage_data == {}
        assert 'Coverage collection returned no data' in capsys.readouterr().err
        assert list(project.glob('.coverage*')) == []

    def it_returns_no_data_and_the_timeout_notice_when_a_shard_outlasts_the_limit(
        self, project: Path, capsys: pytest.CaptureFixture[str], sharded_calls: list[int]
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

        assert sharded_calls == [3]
        assert coverage_data == {}
        assert 'coverage pre-scan exceeded 3s' in capsys.readouterr().err
        assert list(project.glob('.coverage*')) == []


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


_TEMP_FILE_HOLDER = """\
import time

from sample import double


def test_holds_a_temp_file(tmp_path):
    marker = tmp_path / 'marker.txt'
    marker.write_text('x')
    time.sleep(3)
    assert marker.read_text() == 'x'
    assert double(1) == 2
"""

_LATE_TEMP_USER = """\
import time

from sample import double


def test_asks_for_a_temp_dir_late(tmp_path_factory):
    time.sleep(1)
    assert tmp_path_factory.mktemp('late').is_dir()
    assert double(3) == 6
"""


@pytest.fixture
def basetemp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    (tmp_path / 'sample.py').write_text('def double(value):\n    return value * 2\n', encoding='utf-8')
    (tmp_path / 'test_holder.py').write_text(_TEMP_FILE_HOLDER, encoding='utf-8')
    (tmp_path / 'test_late_user.py').write_text(_LATE_TEMP_USER, encoding='utf-8')
    return tmp_path


@pytest.mark.medium
class DescribeParallelPrescanWithABasetempInAddopts:
    def it_records_every_test_even_though_all_shards_were_told_the_same_basetemp(self, basetemp_project: Path) -> None:
        node_ids = ['test_holder.py::test_holds_a_temp_file', 'test_late_user.py::test_asks_for_a_temp_dir_late']
        shared_basetemp = f'--basetemp={(basetemp_project / "shared_basetemp").as_posix()}'

        def mapping(workers: int) -> dict[str, dict[str, list[int]]]:
            return _run_tests_with_coverage(
                node_ids,
                basetemp_project,
                coverage_include=[str((basetemp_project / 'sample.py').resolve())],
                preserved_addopts=shared_basetemp,
                prescan_workers=workers,
            )

        assert mapping(2) == mapping(1)
