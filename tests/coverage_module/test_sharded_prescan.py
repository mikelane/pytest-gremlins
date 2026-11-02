"""Running the pre-scan shards as concurrent processes and combining their coverage data (issue #527)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import coverage
import pytest

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
if behaviour != 'nodata':
    data_file.write_text(json.dumps({'ids': ids, 'cwd': os.getcwd()}), encoding='utf-8')
sys.exit({'crash': 2, 'testsfail': 1}.get(behaviour, 0))
"""


def _run(tmp_path: Path, shards: list[list[str]], *, timeout: int = 30) -> list[Path] | None:
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    return run_prescan_shards(
        [sys.executable, '-c', _FAKE_SHARD],
        shards,
        cwd=tmp_path,
        timeout=timeout,
        env=dict(os.environ),
        scratch_dir=scratch,
    )


@pytest.mark.medium
class DescribeRunPrescanShards:
    def it_returns_one_data_file_per_shard_each_written_by_its_own_process(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok', 'a'], ['ok', 'b'], ['ok', 'c']])

        assert data_files is not None
        recorded = [json.loads(path.read_text(encoding='utf-8'))['ids'] for path in data_files]
        assert recorded == [['ok', 'a'], ['ok', 'b'], ['ok', 'c']]
        assert len(set(data_files)) == 3

    def it_runs_every_shard_in_the_given_directory(self, tmp_path: Path) -> None:
        data_files = _run(tmp_path, [['ok']])

        assert data_files is not None
        assert Path(json.loads(data_files[0].read_text(encoding='utf-8'))['cwd']).resolve() == tmp_path.resolve()

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


@pytest.mark.medium
class DescribeCombineShardData:
    def it_keeps_each_tests_context_on_its_lines(self, tmp_path: Path) -> None:
        _write_shard_data(tmp_path / 's0', 'a.py::test_one', {'/src/m.py': {1, 2}})
        _write_shard_data(tmp_path / 's1', 'b.py::test_two[x-1]', {'/src/m.py': {2, 3}})
        combined = tmp_path / 'combined'

        combine_shard_data([tmp_path / 's0', tmp_path / 's1'], combined)

        data = coverage.CoverageData(basename=str(combined))
        data.read()
        contexts = data.contexts_by_lineno('/src/m.py')
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
