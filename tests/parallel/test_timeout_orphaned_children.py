"""A timed-out gremlin run ends on time and leaves no child processes behind (#975)."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.parallel.persistent_pool import _run_gremlin_batch
from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.parallel.pool import WorkerResult

MUTANT_TIMEOUT_SECONDS = 1
HARD_DEADLINE_SECONDS = 20
LONG_SLEEP_SECONDS = 3600
REAP_DEADLINE_SECONDS = 10
POLL_SECONDS = 0.1

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


def _is_gone(pid: int) -> bool:
    deadline = time.monotonic() + REAP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(POLL_SECONDS)
    return False


def _run_batch_with_deadline(pid_file: Path, cwd: Path) -> tuple[bool, list[WorkerResult]]:
    results: list[WorkerResult] = []

    def run() -> None:
        results.extend(
            _run_gremlin_batch(
                ['g1'],
                [sys.executable, '-c', _HANGING_TEST_PROCESS.format(sleep=LONG_SLEEP_SECONDS), str(pid_file)],
                str(cwd),
                {},
                MUTANT_TIMEOUT_SECONDS,
            )
        )

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(HARD_DEADLINE_SECONDS)
    finished = not worker.is_alive()
    if not finished:
        _kill_if_alive(pid_file)
        worker.join(HARD_DEADLINE_SECONDS)
    return finished, results


@pytest.mark.medium
class DescribeRunGremlinBatchWithOrphanedChildren:
    def it_records_timeout_promptly_when_a_child_keeps_the_output_pipes_open(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        try:
            finished, results = _run_batch_with_deadline(pid_file, tmp_path)
        finally:
            _kill_if_alive(pid_file)

        assert finished
        assert [r.status for r in results] == [GremlinResultStatus.TIMEOUT]

    @pytest.mark.skipif(sys.platform == 'win32', reason='liveness is probed with signal 0, which kills on Windows')
    def it_kills_the_children_of_a_timed_out_test_run(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        try:
            _run_batch_with_deadline(pid_file, tmp_path)
            gone = _is_gone(_grandchild_pid(pid_file))
        finally:
            _kill_if_alive(pid_file)

        assert gone
