"""Adversarial probes of the pool watchdog (issue #976): ways a hung gremlin still outlives its deadline."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    wait,
)
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from pytest_gremlins.parallel.pool import (
    WorkerPool,
    WorkerResult,
)
from pytest_gremlins.parallel.worker_kill import kill_process_tree
from pytest_gremlins.reporting.results import GremlinResultStatus
from tests.parallel.watchdog_workers import run_scripted

HARD_DEADLINE_SECONDS = 50
SLACK_SECONDS = 3
"""Allowance for worker spawns, the 1 s watchdog tick and a loaded machine."""
FOREVER = '3600'


def _submit(pool: WorkerPool, gremlin_id: str, sleep_seconds: str, rootdir: Path) -> Future[WorkerResult]:
    return pool.submit(
        gremlin_id=gremlin_id,
        test_command=[sleep_seconds],
        rootdir=str(rootdir),
        instrumented_dir=None,
        env_vars={},
    )


def _drive(pool: WorkerPool, futures: list[Future[WorkerResult]]) -> dict[int, float]:
    """Drive the watchdog until every future is done; return the monotonic time each future finished at."""
    finished_at: dict[int, float] = {}
    deadline = time.monotonic() + HARD_DEADLINE_SECONDS
    pending = set(futures)
    while pending:
        if time.monotonic() > deadline:
            pytest.fail(f'{len(pending)} future(s) still pending after {HARD_DEADLINE_SECONDS}s: the pool hung')
        pool.service()
        done, pending = wait(pending, timeout=0.1)
        now = time.monotonic()
        finished_at.update({id(future): now for future in done})
    return finished_at


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.large
class DescribeAHungGremlinInFlightWhenAnotherHangIsCaught:
    def it_times_out_within_timeout_plus_grace_of_its_latest_start(self, tmp_path: Path) -> None:
        timeout, grace = 4, 0.5
        pool = WorkerPool(max_workers=2, timeout=timeout, grace_seconds=grace, worker_target=run_scripted)
        with pool:
            first_hung = _submit(pool, 'first-hung', FOREVER, tmp_path)
            quick = _submit(pool, 'quick', '1', tmp_path)
            second_hung = _submit(pool, 'second-hung', FOREVER, tmp_path)
            submitted_at = time.monotonic()
            finished_at = _drive(pool, [first_hung, quick, second_hung])

        # A hung gremlin is scored within timeout + grace of its latest start. second-hung starts about 1 s in,
        # so it has run less than its timeout when first-hung is caught and the pool is rebuilt. It then restarts,
        # and its deadline restarts with it: the bound is one timeout before the rebuild plus timeout + grace after.
        # The reset is bounded per rebuild: every rebuild scores at least one gremlin for good, so the run always
        # progresses, and a gremlin's clock restarts only when another gremlin's hang rebuilds the pool while it is
        # still under its timeout.
        assert finished_at[id(second_hung)] - submitted_at < timeout + timeout + grace + SLACK_SECONDS


def _spawn_orphaning_tree(tmp_path: Path) -> tuple[subprocess.Popen[bytes], Path]:
    """Start a process whose child double-forks a long-lived grandchild, then exits (a daemonized helper)."""
    grandchild_pid_file = tmp_path / 'grandchild.pid'
    script = (
        'import os, subprocess, sys, time\n'
        'helper = subprocess.Popen([sys.executable, "-c", '
        '"import os, sys, time\\n'
        'if os.fork() == 0:\\n'
        '    os.setsid()\\n'
        f'    open({str(grandchild_pid_file)!r}, \\"w\\").write(str(os.getpid()))\\n'
        '    time.sleep(3600)\\n'
        '"])\n'
        'helper.wait()\n'
        'time.sleep(3600)\n'
    )
    worker = subprocess.Popen([sys.executable, '-c', script])
    deadline = time.monotonic() + 10
    while not grandchild_pid_file.exists() or not grandchild_pid_file.read_text():
        if time.monotonic() > deadline:
            worker.kill()
            pytest.fail('the grandchild never started')
        time.sleep(0.05)
    return worker, grandchild_pid_file


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeKillingAWorkerWhoseTestStartedADaemon:
    def it_kills_the_daemonized_grandchild_too(self, tmp_path: Path) -> None:
        worker, grandchild_pid_file = _spawn_orphaning_tree(tmp_path)
        grandchild_pid = int(grandchild_pid_file.read_text())
        try:
            kill_process_tree(worker.pid)
            worker.wait(timeout=10)
            time.sleep(0.2)
            alive = _is_alive(grandchild_pid)
        finally:
            subprocess.run(['kill', '-9', str(grandchild_pid)], check=False, capture_output=True)  # noqa: S607

        assert not alive


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeKillingAWorkerWhenPsIsUnavailable:
    def it_still_kills_the_test_command_the_worker_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        child_pid_file = tmp_path / 'child.pid'
        script = (
            'import subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])\n'
            f'open({str(child_pid_file)!r}, "w").write(str(child.pid))\n'
            'time.sleep(3600)\n'
        )
        worker = subprocess.Popen([sys.executable, '-c', script])
        deadline = time.monotonic() + 10
        while not child_pid_file.exists() or not child_pid_file.read_text():
            assert time.monotonic() < deadline, 'the child never started'
            time.sleep(0.05)
        child_pid = int(child_pid_file.read_text())
        monkeypatch.setenv('PATH', str(tmp_path / 'no-ps-here'))
        try:
            kill_process_tree(worker.pid)
            worker.wait(timeout=10)
            time.sleep(0.2)
            alive = _is_alive(child_pid)
        finally:
            subprocess.run(['/bin/kill', '-9', str(child_pid)], check=False, capture_output=True)

        assert not alive


@pytest.mark.medium
class DescribeTheWatchdogCostOnALongRun:
    def it_does_not_rescan_gremlins_that_already_finished(self) -> None:
        finished = 20_000
        pool = WorkerPool(max_workers=1, timeout=30)
        pool._executor = object()  # type: ignore[assignment]
        pool._dispatch = lambda _job: None  # type: ignore[method-assign,assignment]
        pool._reports = multiprocessing.get_context().SimpleQueue()
        for n in range(finished):
            pool.submit(
                gremlin_id=f'g{n}', test_command=['x'], rootdir='.', instrumented_dir=None, env_vars={}
            ).set_result(WorkerResult(gremlin_id=f'g{n}', status=GremlinResultStatus.SURVIVED, execution_time_ms=0.0))

        calls = 200
        started = time.perf_counter()
        for _ in range(calls):
            pool.service()
        per_call_ms = (time.perf_counter() - started) / calls * 1000

        # service() runs once per completed gremlin, so a per-call cost that grows with finished gremlins makes
        # the run quadratic: about 2 ms per call at 10 000 gremlins is about 20 s of parent CPU over the run.
        assert per_call_ms < 0.5
