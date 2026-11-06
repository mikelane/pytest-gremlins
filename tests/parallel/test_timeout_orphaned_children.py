"""A timed-out gremlin run ends on time even when its test process left children holding the output pipes (#975)."""

from __future__ import annotations

import os
import signal
import sys
import threading
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

# The test process starts a child that inherits stdout and stderr, records its pid, then hangs as a mutant would.
_HANGING_TEST_PROCESS = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({sleep})'])
open(sys.argv[1], 'w').write(str(child.pid))
time.sleep({sleep})
"""


def _kill_if_alive(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        os.kill(int(pid_file.read_text()), signal.SIGKILL)
    except (ProcessLookupError, ValueError):
        return


@pytest.mark.medium
@pytest.mark.skipif(
    sys.platform == 'win32', reason='the hanging child is reaped by the Windows tree kill, tested apart'
)
class DescribeRunGremlinBatchWithOrphanedChildren:
    """POSIX only: CPython kills and reaps the direct child without a second unbounded communicate().

    On Windows ``subprocess.run`` does call ``communicate()`` again after the kill, so a child holding the pipes can
    block it; that case is not covered here because it cannot be reproduced on a POSIX host (see #975).
    """

    def it_records_timeout_promptly_when_a_child_keeps_the_output_pipes_open(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        results: list[WorkerResult] = []

        def run() -> None:
            results.extend(
                _run_gremlin_batch(
                    ['g1'],
                    [sys.executable, '-c', _HANGING_TEST_PROCESS.format(sleep=LONG_SLEEP_SECONDS), str(pid_file)],
                    str(tmp_path),
                    {},
                    MUTANT_TIMEOUT_SECONDS,
                )
            )

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            worker.join(HARD_DEADLINE_SECONDS)
            finished = not worker.is_alive()
        finally:
            _kill_if_alive(pid_file)
            worker.join(HARD_DEADLINE_SECONDS)

        assert finished
        assert [r.status for r in results] == [GremlinResultStatus.TIMEOUT]
