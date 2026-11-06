"""A hung worker cannot hold the run past its gremlin's deadline (issue #976)."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    wait,
)
import logging
import os
from pathlib import Path
import time

import pytest

from pytest_gremlins.parallel.pool import (
    WorkerPool,
    WorkerResult,
)
from pytest_gremlins.reporting.results import GremlinResultStatus
from tests.parallel.watchdog_workers import (
    run_raising,
    run_scripted,
)

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

        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.name == 'pytest_gremlins.parallel.pool' and record.levelno == logging.WARNING
        ]
        assert warnings, 'the pool logged no warning about the hang'
        assert 'hung-gremlin-id' in warnings[0]

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
class DescribeAnotherGremlinThatHasAlreadyOutlivedItsTimeout:
    def it_is_scored_timeout_when_the_pool_is_rebuilt_instead_of_getting_a_fresh_start(self, tmp_path: Path) -> None:
        long_grace = 3
        with WorkerPool(
            max_workers=2, timeout=TIMEOUT_SECONDS, grace_seconds=long_grace, worker_target=run_scripted
        ) as pool:
            first_hung = _submit(pool, 'first-hung', FOREVER, tmp_path)
            quick = _submit(pool, 'quick', '1', tmp_path)
            second_hung = _submit(pool, 'second-hung', FOREVER, tmp_path)
            submitted_at = time.monotonic()
            _results(pool, [first_hung, quick, second_hung])
            settled_after = time.monotonic() - submitted_at

        # first-hung is caught about timeout + grace = 5 s in. second-hung started at 1 s, so it has run 4 s,
        # past its own 2 s timeout: it is scored then, not restarted (a restart would end it at about 10 s).
        assert second_hung.result().status == GremlinResultStatus.TIMEOUT
        assert settled_after < 8


@pytest.mark.medium
class DescribeAWorkerThatRaises:
    def it_hands_the_error_to_the_callers_future(self, tmp_path: Path) -> None:
        with WorkerPool(max_workers=1, timeout=TIMEOUT_SECONDS, worker_target=run_raising) as pool:
            future = _submit(pool, 'raises', '0', tmp_path)
            wait([future], timeout=HARD_DEADLINE_SECONDS)

        error = future.exception(timeout=0)
        assert isinstance(error, RuntimeError)
        assert str(error) == 'worker failed on raises'


@pytest.mark.small
class DescribeServiceOutsideTheContext:
    def it_returns_no_scored_gremlins_before_the_pool_starts(self) -> None:
        assert WorkerPool(max_workers=1).service() == []


@pytest.mark.small
class DescribeAWatchdogThatFails:
    def it_logs_a_warning_and_reraises(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def failing_scoring(_pool: WorkerPool) -> list[str]:
            msg = 'scoring failed'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_score_overdue_gremlins', failing_scoring)
        pool = WorkerPool(max_workers=1)
        pool._executor = object()  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match='scoring failed'):
            pool.service()

        assert [record.levelno for record in caplog.records] == [logging.WARNING]
        assert 'watchdog failed' in caplog.records[0].getMessage()


@pytest.mark.medium
class DescribeTheDeadlineClock:
    def it_starts_when_the_gremlin_starts_not_when_it_is_queued(self, tmp_path: Path) -> None:
        with _pool(1) as pool:
            futures = [_submit(pool, f'slow-{n}', '1', tmp_path) for n in range(4)]
            statuses = {result.status for result in _results(pool, futures)}

        assert statuses == {GremlinResultStatus.SURVIVED}
