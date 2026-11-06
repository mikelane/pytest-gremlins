"""A SIGTERM to the main pytest process ends the test commands it started in their own sessions (#975)."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

pytest_plugins = ['pytester']

STARTUP_DEADLINE_SECONDS = 60
REAP_DEADLINE_SECONDS = 10
POLL_SECONDS = 0.1

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


def _wait_for_file(path: Path) -> int:
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return int(path.read_text())
        time.sleep(POLL_SECONDS)
    msg = f'{path} was not written'
    raise AssertionError(msg)


def _is_gone(pid: int) -> bool:
    deadline = time.monotonic() + REAP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(POLL_SECONDS)
    return False


def _kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


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
    main = subprocess.Popen(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '--gremlins', '--gremlin-targets=calc.py', *mode],
        cwd=pytester.path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    command = 0
    try:
        command = _wait_for_file(pid_file)
        main.send_signal(signal.SIGTERM)
        main.wait(timeout=STARTUP_DEADLINE_SECONDS)
        gone = _is_gone(command)
    finally:
        main.kill()
        if command:
            _kill_quietly(command)

    assert (gone, main.returncode) == (True, -signal.SIGTERM)
