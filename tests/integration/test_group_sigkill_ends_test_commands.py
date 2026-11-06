"""A SIGKILL to the run's whole process group ends its test commands too, as it did before #975.

A CI timeout, ``timeout -s KILL`` and the #974 interrupted-run test kill the group, not one pid. Before #975 every
test command shared that group and died with it. A command in its own session survives, and the worker that
enforced its mutant timeout is gone, so a hanging gremlin runs on with nothing to stop it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from process_helpers import (  # type: ignore[import-not-found]
    is_gone,
    kill_quietly,
    wait_for_pid,
)
import pytest

pytest_plugins = ['pytester']

_SOURCE = 'def add(a, b):\n    return a + b\n'

# Hangs only in a mutation run's test command, the only process with a gremlin active.
_TESTS = """
import os
import pathlib
import time

from calc import add


def test_add():
    if os.environ.get('ACTIVE_GREMLIN'):
        pathlib.Path(os.environ['HANG_PID_FILE']).write_text(str(os.getpid()))
        time.sleep(3600)
    assert add(2, 3) == 5
"""


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and SIGKILL are POSIX')
@pytest.mark.parametrize(
    'mode',
    [
        pytest.param((), id='serial-mutation-run'),
        # One worker, so a single gremlin hangs at a time and the test knows every pid it must clean up.
        pytest.param(('--gremlin-parallel', '--gremlin-workers=1'), id='parallel-mutation-run'),
    ],
)
def it_ends_the_hanging_test_command_when_the_runs_process_group_gets_sigkill(
    pytester: pytest.Pytester, mode: tuple[str, ...]
) -> None:
    pytester.makepyfile(calc=_SOURCE, test_calc=_TESTS)
    pytester.makeini('[pytest]\n')
    pid_file = pytester.path / 'hang.pid'
    env = {**os.environ, 'PYTHONPATH': str(pytester.path), 'HANG_PID_FILE': str(pid_file)}
    gremlins_run = subprocess.Popen(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '--gremlins', '--gremlin-targets=calc.py', *mode],
        cwd=pytester.path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    command_pid = 0
    try:
        command_pid = wait_for_pid(pid_file)
        os.killpg(gremlins_run.pid, signal.SIGKILL)
        gremlins_run.wait()
        is_command_gone = is_gone(command_pid)
    finally:
        gremlins_run.kill()
        kill_quietly(command_pid)

    assert is_command_gone
