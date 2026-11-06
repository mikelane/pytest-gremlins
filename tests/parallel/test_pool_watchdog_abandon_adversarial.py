"""Adversarial QA run 3 probe: the watchdog's last-resort abandon path (issue #976)."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

HARD_DEADLINE_SECONDS = 40
SETTLE_SECONDS = 5

_RUN_WHERE_THE_KILL_FAILS_WITH_A_TEST_COMMAND = """
import sys
from concurrent.futures import wait

from pytest_gremlins.parallel import pool as pool_module
from pytest_gremlins.parallel.pool import WorkerPool
from tests.parallel.watchdog_workers import run_with_test_command


def failing_kill(_pids):
    raise RuntimeError('the process table is unreadable')


def main():
    pool_module.kill_process_trees = failing_kill
    try:
        with WorkerPool(max_workers=1, timeout=1, grace_seconds=0.2, worker_target=run_with_test_command) as pool:
            future = pool.submit('hung', ['3600'], sys.argv[1], None, {})
            while not future.done():
                pool.service()
                wait([future], timeout=0.1)
    except RuntimeError as error:
        print('service raised:', error, flush=True)


if __name__ == '__main__':
    main()
"""


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeAWatchdogThatAbandonsAHungWorkerWithATestCommand:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            'AQA run 3: _abandon_workers SIGKILLs only the workers, so the hung test command is orphaned and '
            'outlives the run'
        ),
    )
    def it_leaves_no_test_command_running_after_the_run_ends(self, tmp_path: Path) -> None:
        script = tmp_path / 'run_where_the_kill_fails.py'
        script.write_text(_RUN_WHERE_THE_KILL_FAILS_WITH_A_TEST_COMMAND)
        repo_root = Path(__file__).resolve().parents[2]
        log_path = tmp_path / 'run.log'
        # A file, not a pipe: an orphaned test command inherits the run's stdout and would hold a pipe open.
        with log_path.open('w') as log:
            run = subprocess.Popen(
                [sys.executable, str(script), str(tmp_path)],
                env={**os.environ, 'PYTHONPATH': str(repo_root)},
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            run.wait(timeout=HARD_DEADLINE_SECONDS)
            finished = True
        except subprocess.TimeoutExpired:
            os.killpg(run.pid, signal.SIGKILL)
            run.wait()
            finished = False
        output = log_path.read_text()
        child_pids = [int(marker.read_text()) for marker in tmp_path.glob('hung.*.child')]
        try:
            time.sleep(SETTLE_SECONDS)
            survivors = [pid for pid in child_pids if _is_alive(pid)]
        finally:
            for pid in child_pids:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, signal.SIGKILL)

        assert finished, f'the run did not end after the watchdog failed; output:\n{output}'
        assert 'service raised: the process table is unreadable' in output, output
        assert child_pids, f'the worker never started its test command; output:\n{output}'
        assert survivors == [], f'test commands still running after the run ended: {survivors}'


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
