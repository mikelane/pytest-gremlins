"""SIGINT on a --gremlin-batch run's main pid alone stops it promptly (issue #1092).

Every gremlin's test command sleeps, so with two workers and many one-gremlin batches the queue would take minutes
to drain. The test signals only the main pid (a CI cancel, ``kill -INT``), not the process group, and expects the
run to exit within a bounded time, cancelling the queued batches and leaving none of its processes behind.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from process_helpers import (  # type: ignore[import-not-found]
    STARTUP_DEADLINE_SECONDS,
    kill_all_quietly,
    pids_with_env_marker,
    wait_until_no_process_has_env_marker,
)
import pytest

STARTUP_LIMIT_SECONDS = 120
"""How long the run may take to reach its first gremlin (collection, coverage and the baseline run come first)."""
EXIT_LIMIT_SECONDS = 30
"""Generous on purpose: draining the queue takes minutes, so only a run that ignores the interrupt overshoots it."""
GREMLIN_TEST_SLEEP_SECONDS = 600
"""Longer than the exit limit and the reap window together, so a test command left running cannot end by itself."""
OUTPUT_TAIL_CHARACTERS = 4000
POLL_SECONDS = 0.2
_RUN_MARKER_NAME = 'GREMLINS_1092_RUN_MARKER'
_RUN_MARKER_VALUE = 'interrupted-batch-run-leaves-nothing-behind'
_RUN_MARKER = f'{_RUN_MARKER_NAME}={_RUN_MARKER_VALUE}'
"""Every process the run starts inherits this variable, so one that outlives the run shows up in ``ps``."""

_TARGET = """
def mix(a, b):
    total = a + b
    total = total - 1
    total = total * 2
    if total > 10:
        return total + 3
    if total < 0:
        return total - 4
    return total * 5
"""

_TEST = """
import os
import time

from calc import mix


def test_mix():
    assert mix(2, 3) == 40
    if os.environ.get('ACTIVE_GREMLIN', 'NONE') != 'NONE':
        open({started!r}, 'a').close()
        time.sleep({sleep})
"""


def _wait_for(path: Path, run: subprocess.Popen[bytes], output: Path) -> None:
    deadline = time.monotonic() + STARTUP_LIMIT_SECONDS
    while time.monotonic() < deadline:
        if path.exists():
            return
        if run.poll() is not None:
            pytest.fail(f'the run exited with {run.returncode} before any gremlin started:\n{_tail(output)}')
        time.sleep(POLL_SECONDS)
    pytest.fail('no gremlin test command started in time')


def _tail(output: Path) -> str:
    return output.read_text(errors='replace')[-OUTPUT_TAIL_CHARACTERS:]


def _exits_within(run: subprocess.Popen[bytes], seconds: float) -> bool:
    try:
        run.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def _kill_group(run: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(run.pid, signal.SIGKILL)
    run.wait(timeout=STARTUP_DEADLINE_SECONDS)


@pytest.mark.medium
@pytest.mark.xdist_group(name='interrupted_batch_run')
@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Windows has no SIGINT for one process: os.kill with SIGINT terminates it instead',
)
class DescribeAnInterruptedBatchRun:
    def it_exits_promptly_on_sigint_to_the_main_pid_and_leaves_no_process_behind(
        self,
        pytester_with_markers: pytest.Pytester,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        started = tmp_path / 'a-gremlin-started'
        output = tmp_path / 'run-output.txt'
        monkeypatch.setenv(_RUN_MARKER_NAME, _RUN_MARKER_VALUE)
        pytester_with_markers.makepyfile(calc=_TARGET)
        pytester_with_markers.makepyfile(test_calc=_TEST.format(started=str(started), sleep=GREMLIN_TEST_SLEEP_SECONDS))

        with output.open('w', encoding='utf-8') as run_output:
            run = pytester_with_markers.popen(
                [
                    sys.executable,
                    '-m',
                    'pytest',
                    '--gremlins',
                    '--gremlin-targets=calc.py',
                    '--gremlin-batch',
                    '--gremlin-batch-size=1',
                    '--gremlin-workers=2',
                    '--gremlin-mutant-timeout=600',
                    '-p',
                    'no:cacheprovider',
                ],
                stdout=run_output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        leftover: list[int] = []
        try:
            _wait_for(started, run, output)
            run.send_signal(signal.SIGINT)
            exited_in_time = _exits_within(run, EXIT_LIMIT_SECONDS)
            # Checked before the clean-up below, which would otherwise end a leftover in the run's own group.
            leftover = wait_until_no_process_has_env_marker(_RUN_MARKER)
        finally:
            _kill_group(run)
            kill_all_quietly(pids_with_env_marker(_RUN_MARKER))

        assert (exited_in_time, leftover) == (True, []), _tail(output)
