"""A timed-out gremlin run ends on time and leaves no child processes behind (#975)."""

from __future__ import annotations

from concurrent.futures import wait
import os
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING

from process_helpers import (  # type: ignore[import-not-found]
    POLL_SECONDS,
    STARTUP_DEADLINE_SECONDS,
    is_gone,
    kill_quietly,
    wait_for_file,
)
import pytest

from pytest_gremlins.parallel.persistent_pool import _run_gremlin_batch
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.reporting.results import GremlinResultStatus
from tests.parallel.watchdog_workers import run_hanging_command_in_run_bounded

if TYPE_CHECKING:
    from concurrent.futures import Future
    from pathlib import Path

    from pytest_gremlins.parallel.pool import WorkerResult

POOL_TIMEOUT_SECONDS = 2
"""The pool's per-gremlin deadline; long enough for the command to write its pids first, under CI load."""
POOL_GRACE_SECONDS = 0.5
MUTANT_TIMEOUT_SECONDS = 1
HARD_DEADLINE_SECONDS = 2 * STARTUP_DEADLINE_SECONDS + 5
LONG_SLEEP_SECONDS = 3600

# The test process starts a child that inherits stdout and stderr, records its pid, then hangs as a mutant would.
_HANGING_TEST_PROCESS = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({sleep})'])
open(sys.argv[1], 'w').write(str(child.pid))
time.sleep({sleep})
"""

_FORCE_KILL = getattr(signal, 'SIGKILL', signal.SIGTERM)


def _grandchild_pid(pid_file: Path) -> int:
    return int(pid_file.read_text())


def _kill_if_alive(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        os.kill(_grandchild_pid(pid_file), _FORCE_KILL)
    except (ProcessLookupError, PermissionError, ValueError):
        return


def _run_batch_with_deadline(
    pid_file: Path, cwd: Path, mutant_timeout: int = MUTANT_TIMEOUT_SECONDS
) -> tuple[bool, list[WorkerResult]]:
    results: list[WorkerResult] = []

    def run() -> None:
        results.extend(
            _run_gremlin_batch(
                ['g1'],
                [sys.executable, '-c', _HANGING_TEST_PROCESS.format(sleep=LONG_SLEEP_SECONDS), str(pid_file)],
                str(cwd),
                {},
                mutant_timeout,
            )
        )

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(HARD_DEADLINE_SECONDS)
    has_finished = not worker.is_alive()
    if not has_finished:
        _kill_if_alive(pid_file)
        worker.join(HARD_DEADLINE_SECONDS)
    return has_finished, results


@pytest.mark.medium
class DescribeRunGremlinBatchWithOrphanedChildren:
    def it_records_timeout_promptly_when_a_child_keeps_the_output_pipes_open(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        try:
            has_finished, results = _run_batch_with_deadline(pid_file, tmp_path)
        finally:
            _kill_if_alive(pid_file)

        assert (has_finished, [r.status for r in results]) == (True, [GremlinResultStatus.TIMEOUT])

    @pytest.mark.skipif(sys.platform == 'win32', reason='liveness is probed with signal 0, which kills on Windows')
    def it_kills_the_children_of_a_timed_out_test_run(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        try:
            # A hung batch makes the deadline helper kill the grandchild itself, so `has_finished` is what proves
            # the batch, not the helper, ended it.
            # The grandchild's pid file must exist when the timeout fires, so the command gets the startup allowance.
            has_finished, _ = _run_batch_with_deadline(pid_file, tmp_path, STARTUP_DEADLINE_SECONDS)
            is_grandchild_gone = is_gone(_grandchild_pid(pid_file))
        finally:
            _kill_if_alive(pid_file)

        assert (has_finished, is_grandchild_gone) == (True, True)


def _drive_until_done(pool: WorkerPool, future: Future[WorkerResult]) -> WorkerResult:
    """Run the pool's watchdog until ``future`` is done; fail rather than hang when it never is."""
    deadline = time.monotonic() + HARD_DEADLINE_SECONDS
    while not future.done():
        if time.monotonic() > deadline:
            pytest.fail(f'no verdict after {HARD_DEADLINE_SECONDS}s: the pool hung')
        pool.service()
        wait([future], timeout=POLL_SECONDS)
    return future.result()


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signal-0 liveness probes are POSIX')
class DescribeDeadlineKillOfAWorkerRunningABoundedCommand:
    def it_ends_the_command_and_its_grandchild_when_the_pool_kills_the_hung_worker(self, tmp_path: Path) -> None:
        # The command leads its own session (#975), so the pool's kill of the hung worker (#976) must still reach
        # it. Both ignore SIGTERM, and run_bounded's own timeout is far past the pool's.
        command_pid = grandchild_pid = 0
        try:
            with WorkerPool(
                max_workers=1,
                timeout=POOL_TIMEOUT_SECONDS,
                grace_seconds=POOL_GRACE_SECONDS,
                worker_target=run_hanging_command_in_run_bounded,
            ) as pool:
                future = pool.submit('hung', [str(LONG_SLEEP_SECONDS)], str(tmp_path), None, {})
                status = _drive_until_done(pool, future).status
            command_pid, grandchild_pid = map(int, wait_for_file(tmp_path / 'hung.pids').split())
            is_command_gone = is_gone(command_pid)
            is_grandchild_gone = is_gone(grandchild_pid)
        finally:
            kill_quietly(command_pid)
            kill_quietly(grandchild_pid)

        assert (status, is_command_gone, is_grandchild_gone) == (GremlinResultStatus.TIMEOUT, True, True)
