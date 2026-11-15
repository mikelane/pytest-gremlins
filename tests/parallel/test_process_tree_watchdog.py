"""A test command ends when the process that started it dies, however it dies, SIGKILL included (#975).

A command runs in its own session, so a signal sent to the caller's process group no longer reaches it, and SIGKILL
cannot be handled. The calling process therefore keeps a small watchdog process, in its own session, that holds the
read end of a pipe the caller holds the write end of. When the caller dies the pipe reaches end-of-file and the
watchdog kills the command's process group.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from process_helpers import (  # type: ignore[import-not-found]
    REAP_DEADLINE_SECONDS,
    STARTUP_DEADLINE_SECONDS,
    is_gone,
    kill_quietly,
    python,
    wait_for_file,
)
import pytest

LONG_SLEEP_SECONDS = 3600

pytestmark = [
    pytest.mark.medium,
    pytest.mark.skipif(sys.platform == 'win32', reason='process groups and SIGKILL are POSIX'),
]

# The command starts a grandchild in its group and reports both pids.
_COMMAND = (
    'import os, subprocess, sys, time\n'
    f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({LONG_SLEEP_SECONDS})"])\n'
    'open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")\n'
    f'time.sleep({LONG_SLEEP_SECONDS})\n'
)


def _caller_source(tmp_path: Path, *, fork_a_bystander: bool) -> str:
    bystander = (
        f'bystander = os.fork()\nif bystander == 0:\n    time.sleep({LONG_SLEEP_SECONDS})\n    os._exit(0)\n'
        if fork_a_bystander
        else 'bystander = 0\n'
    )
    return (
        'import os, sys, threading, time\n'
        'from pytest_gremlins import process_tree\n'
        f'command = [sys.executable, "-c", {_COMMAND!r}, {str(tmp_path / "command.pids")!r}]\n'
        'threading.Thread(target=process_tree.run_bounded, args=(command,), daemon=True,'
        f' kwargs=dict(cwd={str(tmp_path)!r}, env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})).start()\n'
        'while process_tree.live_command_count() == 0 or process_tree.watchdog_pid() is None:\n'
        '    time.sleep(0.05)\n'
        f'{bystander}'
        f'open({str(tmp_path / "caller.ready")!r}, "w").write(f"{{process_tree.watchdog_pid()}} {{bystander}}")\n'
        f'time.sleep({LONG_SLEEP_SECONDS})\n'
    )


def _start_caller(tmp_path: Path, *, fork_a_bystander: bool = False) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        python(_caller_source(tmp_path, fork_a_bystander=fork_a_bystander)),
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _pids(path: Path) -> list[int]:
    return [int(pid) for pid in wait_for_file(path).split()]


class DescribeWatchdog:
    def it_ends_the_command_and_its_grandchild_when_only_the_caller_is_sigkilled(self, tmp_path: Path) -> None:
        caller = _start_caller(tmp_path)
        command_pid = grandchild_pid = 0
        try:
            command_pid, grandchild_pid = _pids(tmp_path / 'command.pids')
            wait_for_file(tmp_path / 'caller.ready')
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = is_gone(command_pid)
            is_grandchild_gone = is_gone(grandchild_pid)
        finally:
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            kill_quietly(command_pid)
            kill_quietly(grandchild_pid)

        assert (is_command_gone, is_grandchild_gone) == (True, True)

    def it_ends_the_command_when_a_forked_bystander_outlives_the_caller(self, tmp_path: Path) -> None:
        # A forked pool worker copies the caller's file descriptors. It must not keep the watchdog's pipe open.
        caller = _start_caller(tmp_path, fork_a_bystander=True)
        command_pid = bystander_pid = 0
        try:
            command_pid, _ = _pids(tmp_path / 'command.pids')
            _, bystander_pid = _pids(tmp_path / 'caller.ready')
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = is_gone(command_pid)
        finally:
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            kill_quietly(command_pid)
            kill_quietly(bystander_pid)

        assert is_command_gone

    def it_exits_once_the_caller_is_gone(self, tmp_path: Path) -> None:
        caller = _start_caller(tmp_path)
        watchdog_pid = command_pid = 0
        try:
            command_pid, _ = _pids(tmp_path / 'command.pids')
            watchdog_pid, _ = _pids(tmp_path / 'caller.ready')
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_watchdog_gone = is_gone(watchdog_pid)
        finally:
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            kill_quietly(watchdog_pid)
            kill_quietly(command_pid)

        assert is_watchdog_gone

    def it_leaves_a_bystander_alone_after_a_command_finished(self) -> None:
        # The watchdog forgets a command once it is reaped; a later process that reuses the pid is not its to kill.
        bystander = subprocess.Popen(python(f'import time; time.sleep({LONG_SLEEP_SECONDS})'))
        runner = (
            'import os, sys, time\n'
            'from pytest_gremlins import process_tree\n'
            'process_tree.run_bounded([sys.executable, "-c", "pass"], cwd=os.getcwd(), env=dict(os.environ),'
            ' timeout=30)\n'
        )
        try:
            subprocess.run(python(runner), check=True, timeout=STARTUP_DEADLINE_SECONDS)
            time.sleep(1)
            is_bystander_alive = bystander.poll() is None
        finally:
            bystander.kill()
            bystander.wait(timeout=REAP_DEADLINE_SECONDS)

        assert is_bystander_alive

    def it_starts_no_watchdog_until_a_command_runs(self) -> None:
        runner = 'from pytest_gremlins import process_tree\nprint(process_tree.watchdog_pid())\n'

        completed = subprocess.run(python(runner), capture_output=True, check=True, timeout=STARTUP_DEADLINE_SECONDS)

        assert completed.stdout.strip() == b'None'

    def it_ends_the_command_when_the_callers_whole_process_group_is_sigkilled(self, tmp_path: Path) -> None:
        # The watchdog leads its own session, so a SIGKILL to the caller's group does not take it down too.
        caller = _start_caller(tmp_path)
        watchdog_pid = command_pid = 0
        try:
            command_pid, _ = _pids(tmp_path / 'command.pids')
            watchdog_pid, _ = _pids(tmp_path / 'caller.ready')
            os.killpg(caller.pid, signal.SIGKILL)
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = is_gone(command_pid)
        finally:
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            kill_quietly(watchdog_pid)
            kill_quietly(command_pid)

        assert is_command_gone

    def it_reaps_its_watchdog_at_a_normal_exit_without_a_warning(self) -> None:
        runner = (
            'import os, sys\n'
            'from pytest_gremlins import process_tree\n'
            'process_tree.run_bounded([sys.executable, "-c", "pass"], cwd=os.getcwd(), env=dict(os.environ),'
            ' timeout=30)\n'
        )

        completed = subprocess.run(
            [sys.executable, '-X', 'dev', '-W', 'error::ResourceWarning', '-c', runner],
            capture_output=True,
            check=False,
            timeout=STARTUP_DEADLINE_SECONDS,
        )

        assert (completed.returncode, completed.stderr) == (0, b'')
