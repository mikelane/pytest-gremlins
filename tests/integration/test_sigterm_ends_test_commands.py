"""A SIGTERM to the main pytest process ends the test commands it started in their own sessions (#975)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from process_helpers import (  # type: ignore[import-not-found]
    STARTUP_DEADLINE_SECONDS,
    is_gone,
    kill_quietly,
    wait_for_pid,
)
import pytest

pytest_plugins = ['pytester']


_SOURCE = 'def add(a, b):\n    return a + b\n'

# The test hangs only in a command that run_bounded started (such a command leads its own session), and only in
# the phase under test: the pre-scan runs it with no gremlin active, a mutation run with one. The baseline run is the
# main pytest process itself, which leads no session, so it passes.
_HANG_IN_PRE_SCAN = 'os.getsid(0) == os.getpid()'
_HANG_IN_MUTATION_RUN = "os.getsid(0) == os.getpid() and os.environ.get('ACTIVE_GREMLIN')"

_TESTS = """
import os
import pathlib
import time

from calc import add


def test_add():
    if HANG_CONDITION:
        pathlib.Path(os.environ['HANG_PID_FILE']).write_text(str(os.getpid()))
        time.sleep(3600)
    assert add(2, 3) == 5
"""


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM and sessions are POSIX')
@pytest.mark.parametrize(
    ('hang_condition', 'mode'),
    [
        pytest.param(_HANG_IN_PRE_SCAN, (), id='pre-scan'),
        pytest.param(_HANG_IN_MUTATION_RUN, (), id='serial-mutation-run'),
        pytest.param(
            _HANG_IN_MUTATION_RUN,
            ('--gremlin-parallel', '--gremlin-workers=2'),
            id='parallel-mutation-run',
        ),
        pytest.param(_HANG_IN_MUTATION_RUN, ('--gremlin-batch',), id='batch-mutation-run'),
        pytest.param(
            _HANG_IN_MUTATION_RUN,
            ('--gremlin-batch', '--gremlin-parallel', '--gremlin-workers=2'),
            id='parallel-batch-mutation-run',
        ),
    ],
)
def it_ends_the_hanging_test_command_when_the_main_process_gets_sigterm(
    pytester: pytest.Pytester, hang_condition: str, mode: tuple[str, ...]
) -> None:
    pytester.makepyfile(calc=_SOURCE, test_calc=_TESTS.replace('HANG_CONDITION', hang_condition))
    pytester.makeini('[pytest]\n')
    pid_file = pytester.path / 'hang.pid'
    env = {**os.environ, 'PYTHONPATH': str(pytester.path), 'HANG_PID_FILE': str(pid_file)}
    gremlins_run = subprocess.Popen(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '--gremlins', '--gremlin-targets=calc.py', *mode],
        cwd=pytester.path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    command_pid = 0
    try:
        command_pid = wait_for_pid(pid_file)
        gremlins_run.send_signal(signal.SIGTERM)
        gremlins_run.wait(timeout=STARTUP_DEADLINE_SECONDS)
        is_command_gone = is_gone(command_pid)
    finally:
        gremlins_run.kill()
        kill_quietly(command_pid)

    assert (is_command_gone, gremlins_run.returncode) == (True, -signal.SIGTERM)
