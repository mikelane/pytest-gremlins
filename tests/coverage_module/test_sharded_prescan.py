"""Running the pre-scan shards as concurrent processes and combining their coverage data (issue #527)."""

from __future__ import annotations

from collections.abc import Sequence
import gc
import getpass
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import warnings

import coverage
import pytest

from pytest_gremlins.coverage import sharded_prescan
from pytest_gremlins.coverage.sharded_prescan import (
    combine_shard_data,
    run_prescan_shards,
    run_sharded_prescan,
)

# Stands in for ``coverage run -m pytest_gremlins.coverage.prescan_main``: it reads the shard's node-id file, whose
# first id names the behaviour, and writes a data file where COVERAGE_FILE says.
_FAKE_SHARD = """
import json, os, pathlib, sys, time
option = next(a for a in sys.argv[1:] if a.startswith('--gremlins-node-ids-file='))
ids = json.loads(pathlib.Path(option.split('=', 1)[1]).read_text(encoding='utf-8'))
behaviour = ids[0]
data_file = pathlib.Path(os.environ['COVERAGE_FILE'])
if behaviour == 'hang':
    time.sleep(60)
if behaviour == 'crash':
    sys.stderr.write('x' * 5000 + 'WinError 5 access denied')
if behaviour != 'nodata':
    data_file.write_text(
        json.dumps(
            {
                'ids': ids,
                'cwd': os.getcwd(),
                'argv': sys.argv[1:],
                'dont_write_bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE'),
            }
        ),
        encoding='utf-8',
    )
sys.exit({'crash': 2, 'testsfail': 1}.get(behaviour, 0))
"""


@pytest.fixture
def started_shards(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    started: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(subprocess, 'Popen', recording_popen)
    return started


def _run(tmp_path: Path, shards: list[list[str]], *, timeout: int = 30) -> list[Path] | None:
    scratch = tmp_path / 'scratch'
    scratch.mkdir(exist_ok=True)
    return run_prescan_shards(
        [sys.executable, '-c', _FAKE_SHARD],
        shards,
        cwd=tmp_path,
        timeout=timeout,
        env=dict(os.environ),
        scratch_dir=scratch,
    )


def _last_basetemp(data_file: Path) -> str:
    argv: list[str] = json.loads(data_file.read_text(encoding='utf-8'))['argv']
    return [argument for argument in argv if argument.startswith('--basetemp=')][-1]


def _recorded(data_file: Path) -> dict[str, Any]:
    recorded: dict[str, Any] = json.loads(data_file.read_text(encoding='utf-8'))
    return recorded


@pytest.mark.medium
class DescribeRunPrescanShards:
    def it_returns_one_data_file_per_shard_each_written_by_its_own_process(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok', 'a'], ['ok', 'b'], ['ok', 'c']])

        assert data_files == [tmp_path / 'scratch' / str(index) / 'coverage.data' for index in range(3)]
        assert data_files is not None
        recorded = [json.loads(path.read_text(encoding='utf-8'))['ids'] for path in data_files]
        assert recorded == [['ok', 'a'], ['ok', 'b'], ['ok', 'c']]
        assert len(set(data_files)) == 3

    def it_runs_every_shard_in_the_given_directory(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok']])

        assert data_files is not None
        assert Path(json.loads(data_files[0].read_text(encoding='utf-8'))['cwd']).resolve() == tmp_path.resolve()

    def it_gives_each_shard_its_own_basetemp_inside_the_scratch_directory(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok', 'a'], ['ok', 'b']])

        assert data_files is not None
        basetemps = [_last_basetemp(path) for path in data_files]
        assert basetemps == [f'--basetemp={tmp_path / "scratch" / str(index) / "b"}' for index in range(2)]

    def it_keeps_each_shard_basetemp_no_longer_than_pytests_default_basetemp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shard's ``tmp_path`` must stay short enough to bind an AF_UNIX socket (104 bytes on macOS)."""
        real_run = sharded_prescan.run_prescan_shards
        basetemps: list[str] = []

        def run_fake_shards(_command: Sequence[str], shards: Sequence[Sequence[str]], **kwargs: Any) -> None:
            data_files = real_run([sys.executable, '-c', _FAKE_SHARD], shards, **kwargs)
            assert data_files is not None
            basetemps.extend(_last_basetemp(path).removeprefix('--basetemp=') for path in data_files)

        monkeypatch.setattr(sharded_prescan, 'run_prescan_shards', run_fake_shards)
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')

        sharded_prescan.run_sharded_prescan(
            ['unused'],
            ['ok', 'a', 'b', 'c'],
            worker_count=4,
            cwd=tmp_path,
            timeout=30,
            env=dict(os.environ),
            combined=tmp_path / 'combined',
        )

        pytest_default = Path(tempfile.gettempdir()) / f'pytest-of-{getpass.getuser()}' / 'pytest-9999'
        assert len(basetemps) == 4
        assert len(set(basetemps)) == 4
        assert max(len(path) for path in basetemps) <= len(str(pytest_default))

    def _shard_basetemps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], **options: Any
    ) -> list[str]:
        real_run = sharded_prescan.run_prescan_shards
        basetemps: list[str] = []

        def run_fake_shards(_command: Sequence[str], shards: Sequence[Sequence[str]], **kwargs: Any) -> None:
            data_files = real_run([sys.executable, '-c', _FAKE_SHARD], shards, **kwargs)
            assert data_files is not None
            basetemps.extend(_last_basetemp(path).removeprefix('--basetemp=') for path in data_files)

        monkeypatch.setattr(sharded_prescan, 'run_prescan_shards', run_fake_shards)
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        sharded_prescan.run_sharded_prescan(
            ['unused'],
            ['ok', 'a', 'b'],
            worker_count=3,
            cwd=tmp_path,
            timeout=30,
            env=env,
            combined=tmp_path / 'combined',
            **options,
        )
        return basetemps

    def it_places_each_shard_basetemp_under_the_users_basetemp_by_shard_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_basetemp = tmp_path / 'short'

        basetemps = self._shard_basetemps(tmp_path, monkeypatch, dict(os.environ), user_basetemp=user_basetemp)

        assert basetemps == [str(user_basetemp / str(index)) for index in range(3)]

    def it_places_the_scratch_directory_under_pytest_debug_temproot_when_there_is_no_user_basetemp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        temproot = tmp_path / 'temproot'
        temproot.mkdir()
        env = {**os.environ, 'PYTEST_DEBUG_TEMPROOT': str(temproot)}

        basetemps = self._shard_basetemps(tmp_path, monkeypatch, env)

        assert len(basetemps) == 3
        assert all(Path(path).relative_to(temproot.resolve()).parts[0].startswith('pgs') for path in basetemps)
        assert all(Path(path).name == 'b' for path in basetemps)

    def it_prefers_the_users_basetemp_over_pytest_debug_temproot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_basetemp = tmp_path / 'short'
        env = {**os.environ, 'PYTEST_DEBUG_TEMPROOT': str(tmp_path / 'ignored')}

        basetemps = self._shard_basetemps(tmp_path, monkeypatch, env, user_basetemp=user_basetemp)

        assert basetemps == [str(user_basetemp / str(index)) for index in range(3)]

    def it_removes_the_shard_directories_it_made_inside_the_users_basetemp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_basetemp = tmp_path / 'short'

        self._shard_basetemps(tmp_path, monkeypatch, dict(os.environ), user_basetemp=user_basetemp)

        assert list(user_basetemp.iterdir()) == []

    def it_puts_the_basetemp_after_everything_else_so_it_overrides_addopts(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok']])

        assert data_files is not None
        argv = json.loads(data_files[0].read_text(encoding='utf-8'))['argv']
        assert argv[-1].startswith('--basetemp=')

    def it_points_each_shard_pytest_cache_into_its_own_shard_directory(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok', 'a'], ['ok', 'b']])

        assert data_files is not None
        cache_options = [_recorded(path)['argv'][-3:-1] for path in data_files]
        assert cache_options == [
            ['-o', f'cache_dir={tmp_path / "scratch" / str(index) / "cache"}'] for index in range(2)
        ]

    def it_stops_every_shard_from_writing_bytecode_into_the_project(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok', 'a'], ['ok', 'b']])

        assert data_files is not None
        assert [_recorded(path)['dont_write_bytecode'] for path in data_files] == ['1', '1']

    def it_logs_the_exit_code_and_stderr_tail_of_a_crashed_shard(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=sharded_prescan.__name__):
            _run(tmp_path, [['ok'], ['crash']])

        assert 'shard 1 exited with code 2' in caplog.text
        assert 'WinError 5 access denied' in caplog.text

    def it_bounds_the_stderr_tail_it_logs(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=sharded_prescan.__name__):
            _run(tmp_path, [['crash']])

        tail = 'x' * (1000 - len('WinError 5 access denied')) + 'WinError 5 access denied'
        assert f"output tail: '{tail}'" in caplog.text

    def it_prints_the_failed_shard_and_its_exit_code_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(tmp_path, [['ok'], ['crash']])

        assert 'shard 1 exited with code 2' in capsys.readouterr().err

    def it_logs_a_shard_that_left_no_data(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=sharded_prescan.__name__):
            _run(tmp_path, [['nodata']])

        assert 'shard 0 left no coverage data' in caplog.text

    def it_logs_nothing_when_every_shard_succeeds(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger=sharded_prescan.__name__):
            _run(tmp_path, [['ok'], ['testsfail']])

        assert caplog.text == ''

    def it_treats_failing_tests_as_a_finished_shard(self, tmp_path: Path) -> None:
        assert _run(tmp_path, [['ok'], ['testsfail']]) is not None

    def it_reports_a_crashed_shard_as_failure(self, tmp_path: Path) -> None:
        assert _run(tmp_path, [['ok'], ['crash']]) is None

    def it_reports_a_shard_that_left_no_data_as_failure(self, tmp_path: Path) -> None:
        assert _run(tmp_path, [['ok'], ['nodata']]) is None

    def it_stops_waiting_on_a_slow_shard_once_another_has_failed(self, tmp_path: Path) -> None:
        started = time.monotonic()

        outcome = _run(tmp_path, [['hang'], ['crash']], timeout=30)

        assert outcome is None
        assert time.monotonic() - started < 20

    def it_raises_a_timeout_when_the_shards_outlast_the_limit(self, tmp_path: Path) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            _run(tmp_path, [['ok'], ['hang']], timeout=2)

    def it_kills_the_hung_shard_when_the_shards_outlast_the_limit(
        self, tmp_path: Path, started_shards: list[subprocess.Popen[bytes]]
    ) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            _run(tmp_path, [['hang'], ['hang']], timeout=2)

        assert [process.returncode == 0 for process in started_shards] == [False, False]
        assert [process.poll() is not None for process in started_shards] == [True, True]

    def it_kills_a_running_shard_when_a_later_shard_cannot_be_launched(
        self, tmp_path: Path, started_shards: list[subprocess.Popen[bytes]]
    ) -> None:
        (tmp_path / 'scratch' / '1').mkdir(parents=True)

        with pytest.raises(FileExistsError):
            _run(tmp_path, [['hang'], ['ok']])

        assert [process.returncode == 0 for process in started_shards] == [False]
        assert [process.poll() is not None for process in started_shards] == [True]

    def it_raises_when_a_shard_cannot_be_started(self, tmp_path: Path) -> None:
        scratch = tmp_path / 'scratch'
        scratch.mkdir()

        with pytest.raises(OSError):  # noqa: PT011 - the exact subclass is the platform's choice
            run_prescan_shards(
                [str(tmp_path / 'no-such-interpreter')],
                [['ok']],
                cwd=tmp_path,
                timeout=5,
                env=dict(os.environ),
                scratch_dir=scratch,
            )


def _write_shard_data(path: Path, test_name: str, lines_by_file: dict[str, set[int]]) -> None:
    data = coverage.CoverageData(basename=str(path))
    data.set_context(test_name)
    data.add_lines({file: dict.fromkeys(lines) for file, lines in lines_by_file.items()})
    data.write()
    data.close()


@pytest.mark.medium
class DescribeCombineShardData:
    def it_keeps_each_tests_context_on_its_lines(self, tmp_path: Path) -> None:
        # coverage.py canonicalizes paths, so a POSIX-style '/src/m.py' turns into a drive path on Windows.
        source = str((tmp_path / 'm.py').resolve())
        _write_shard_data(tmp_path / 's0', 'a.py::test_one', {source: {1, 2}})
        _write_shard_data(tmp_path / 's1', 'b.py::test_two[x-1]', {source: {2, 3}})
        combined = tmp_path / 'combined'

        combine_shard_data([tmp_path / 's0', tmp_path / 's1'], combined)

        data = coverage.CoverageData(basename=str(combined))
        data.read()
        contexts = data.contexts_by_lineno(source)
        data.close()
        assert {line: sorted(names) for line, names in contexts.items()} == {
            1: ['a.py::test_one'],
            2: ['a.py::test_one', 'b.py::test_two[x-1]'],
            3: ['b.py::test_two[x-1]'],
        }


@pytest.mark.medium
class DescribeRunShardedPrescan:
    def _run(self, tmp_path: Path, node_ids: list[str], combined: Path) -> bool:
        return run_sharded_prescan(
            [sys.executable, '-c', _FAKE_SHARD],
            node_ids,
            worker_count=2,
            cwd=tmp_path,
            timeout=30,
            env=dict(os.environ),
            combined=combined,
        )

    def it_reports_failure_and_writes_nothing_when_a_shard_crashes(self, tmp_path: Path) -> None:
        combined = tmp_path / 'combined'

        assert self._run(tmp_path, ['crash', 'ok'], combined) is False
        assert not combined.exists()

    def it_reports_failure_and_writes_nothing_when_the_shard_data_cannot_be_combined(self, tmp_path: Path) -> None:
        combined = tmp_path / 'combined'

        # The fake shards write JSON, not a coverage database, which is what a corrupt data file looks like.
        assert self._run(tmp_path, ['ok', 'ok2'], combined) is False
        assert not combined.exists()

    def it_reports_failure_and_writes_nothing_when_combining_hits_an_operating_system_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def disk_error(_data_files: Sequence[Path], _combined: Path) -> None:
            raise OSError('disk error while combining')

        monkeypatch.setattr(sharded_prescan, 'combine_shard_data', disk_error)
        combined = tmp_path / 'combined'

        assert self._run(tmp_path, ['ok', 'ok2'], combined) is False
        assert not combined.exists()

    def it_leaves_no_unclosed_database_connection_behind_when_the_shard_data_cannot_be_combined(
        self, tmp_path: Path
    ) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self._run(tmp_path, ['ok', 'ok2'], tmp_path / 'combined')
            gc.collect()

        assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []
