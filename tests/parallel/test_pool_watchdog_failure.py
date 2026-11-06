"""When the watchdog itself fails, the pool still does not wait on the hung worker (issue #976)."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

HARD_DEADLINE_SECONDS = 40

_RUN_WHERE_THE_KILL_FAILS = """
import sys
from concurrent.futures import wait

from pytest_gremlins.parallel import pool as pool_module
from pytest_gremlins.parallel.pool import WorkerPool
from tests.parallel.watchdog_workers import run_scripted


def failing_kill(_pids):
    raise RuntimeError('the process table is unreadable')


def main():
    pool_module.kill_process_trees = failing_kill
    try:
        with WorkerPool(max_workers=1, timeout=1, grace_seconds=0.2, worker_target=run_scripted) as pool:
            future = pool.submit('hung', ['3600'], sys.argv[1], None, {})
            while not future.done():
                pool.service()
                wait([future], timeout=0.1)
    except RuntimeError as error:
        print('service raised:', error, flush=True)
        return
    print('service did not raise', flush=True)


if __name__ == '__main__':
    main()
"""


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeAWatchdogThatFailsWhileKilling:
    def it_raises_and_leaves_no_run_waiting_on_the_hung_worker(self, tmp_path: Path) -> None:
        script = tmp_path / 'run_where_the_kill_fails.py'
        script.write_text(_RUN_WHERE_THE_KILL_FAILS)
        repo_root = Path(__file__).resolve().parents[2]
        run = subprocess.Popen(
            [sys.executable, str(script), str(tmp_path)],
            env={**os.environ, 'PYTHONPATH': str(repo_root)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            output, _ = run.communicate(timeout=HARD_DEADLINE_SECONDS)
            finished = True
        except subprocess.TimeoutExpired:
            os.killpg(run.pid, signal.SIGKILL)
            output, _ = run.communicate()
            finished = False

        assert finished, f'the run waited on the hung worker after the watchdog failed; output:\n{output}'
        assert 'service raised: the process table is unreadable' in output
        hung_pid = int((tmp_path / 'hung.pid').read_text())
        assert not _is_alive(hung_pid)


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
