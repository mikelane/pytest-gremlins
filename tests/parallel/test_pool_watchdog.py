"""A hung worker cannot hold the run past its gremlin's deadline (issue #976)."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    wait,
)
import os
from pathlib import Path
import time

import pytest

from pytest_gremlins.parallel.pool import (
    WorkerPool,
    WorkerResult,
)
from pytest_gremlins.reporting.results import GremlinResultStatus
from tests.parallel.watchdog_workers import run_scripted

HARD_DEADLINE_SECONDS = 40
TIMEOUT_SECONDS = 2
GRACE_SECONDS = 0.5
FOREVER = '3600'


def _pool(max_workers: int) -> WorkerPool:
    return WorkerPool(
        max_workers=max_workers, timeout=TIMEOUT_SECONDS, grace_seconds=GRACE_SECONDS, worker_target=run_scripted
    )


def _submit(pool: WorkerPool, gremlin_id: str, sleep_seconds: str, rootdir: Path) -> Future[WorkerResult]:
    return pool.submit(
        gremlin_id=gremlin_id,
        test_command=[sleep_seconds],
        rootdir=str(rootdir),
        instrumented_dir=None,
        env_vars={},
    )


def _results(pool: WorkerPool, futures: list[Future[WorkerResult]]) -> list[WorkerResult]:
    """Drive the pool's watchdog until every future is done; fail rather than hang when one never is."""
    deadline = time.monotonic() + HARD_DEADLINE_SECONDS
    pending = set(futures)
    while pending:
        if time.monotonic() > deadline:
            pytest.fail(f'{len(pending)} future(s) still pending after {HARD_DEADLINE_SECONDS}s: the pool hung')
        pool.service()
        _, pending = wait(pending, timeout=0.2)
    return [future.result() for future in futures]


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.medium
class DescribeAWorkerThatHangsOutsideTheTestRun:
    def it_records_timeout_for_the_hung_gremlin_and_still_finishes_the_others(self, tmp_path: Path) -> None:
        with _pool(2) as pool:
            hung = _submit(pool, 'hung', FOREVER, tmp_path)
            quick = _submit(pool, 'quick', '0', tmp_path)
            hung_result, quick_result = _results(pool, [hung, quick])

        assert (hung_result.status, quick_result.status) == (GremlinResultStatus.TIMEOUT, GremlinResultStatus.SURVIVED)

    def it_names_the_hung_gremlin_in_a_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with _pool(2) as pool:
            _results(pool, [_submit(pool, 'hung-gremlin-id', FOREVER, tmp_path)])

        assert 'hung-gremlin-id' in caplog.text

    def it_kills_the_hung_worker(self, tmp_path: Path) -> None:
        with _pool(2) as pool:
            _results(pool, [_submit(pool, 'hung', FOREVER, tmp_path)])
            hung_pid = int((tmp_path / 'hung.pid').read_text())

        assert not _is_alive(hung_pid)

    def it_runs_gremlins_that_were_queued_behind_the_hung_one(self, tmp_path: Path) -> None:
        with _pool(1) as pool:
            futures = [_submit(pool, 'hung', FOREVER, tmp_path)]
            futures += [_submit(pool, f'queued-{n}', '0', tmp_path) for n in range(3)]
            statuses = [result.status for result in _results(pool, futures)]

        assert statuses == [GremlinResultStatus.TIMEOUT] + [GremlinResultStatus.SURVIVED] * 3

    def it_keeps_the_verdict_of_a_gremlin_in_flight_on_another_worker(self, tmp_path: Path) -> None:
        with _pool(2) as pool:
            futures = [
                _submit(pool, 'hung', FOREVER, tmp_path),
                _submit(pool, 'first', '1.5', tmp_path),
                _submit(pool, 'second', '1.5', tmp_path),
            ]
            statuses = [result.status for result in _results(pool, futures)]

        assert statuses == [GremlinResultStatus.TIMEOUT, GremlinResultStatus.SURVIVED, GremlinResultStatus.SURVIVED]


@pytest.mark.medium
class DescribeTheDeadlineClock:
    def it_starts_when_the_gremlin_starts_not_when_it_is_queued(self, tmp_path: Path) -> None:
        with _pool(1) as pool:
            futures = [_submit(pool, f'slow-{n}', '1', tmp_path) for n in range(4)]
            statuses = {result.status for result in _results(pool, futures)}

        assert statuses == {GremlinResultStatus.SURVIVED}
