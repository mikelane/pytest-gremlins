"""A timed-out gremlin run ends on time and leaves no child processes behind (#975)."""

from __future__ import annotations

import os
import signal
import sys
import threading
from typing import TYPE_CHECKING

from process_helpers import (  # type: ignore[import-not-found]
    STARTUP_DEADLINE_SECONDS,
    is_gone,
)
import pytest

from pytest_gremlins.parallel.persistent_pool import _run_gremlin_batch
from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.parallel.pool import WorkerResult

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

        assert has_finished
        assert [r.status for r in results] == [GremlinResultStatus.TIMEOUT]

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
