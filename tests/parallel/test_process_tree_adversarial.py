"""Adversarial probes of run_bounded (#975): signals aimed at the caller, interrupts mid-kill, cost and leaks."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

if TYPE_CHECKING:
    from types import FrameType

REAP_DEADLINE_SECONDS = 10
POLL_SECONDS = 0.1
STARTUP_DEADLINE_SECONDS = 15
LONG_SLEEP_SECONDS = 3600
SHORT_TIMEOUT_SECONDS = 1.0
MID_GRACE_SECONDS = 1.25
ONE_MEBIBYTE = 1024 * 1024
REPEATED_RUNS = 20

posix_only = pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')


def _python(code: str) -> list[str]:
    return [sys.executable, '-c', code]


def _run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return run_bounded(command, cwd=str(cwd), env=dict(os.environ), timeout=timeout)


def _wait_for_file(path: Path) -> str:
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
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


def _open_fd_count() -> int:
    return len(list(Path('/dev/fd').iterdir()))


def _sleeper_writing_pid(pid_file: Path, *, ignore_sigterm: bool = False) -> str:
    ignore = 'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n' if ignore_sigterm else ''
    return (
        'import os, signal, time\n'
        f'{ignore}'
        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
        f'time.sleep({LONG_SLEEP_SECONDS})\n'
    )


@pytest.mark.medium
@posix_only
class DescribeRunBoundedUnderSignalsAimedAtTheCaller:
    def it_ends_the_command_when_the_callers_process_group_is_terminated(self, tmp_path: Path) -> None:
        # `timeout 600 pytest --gremlins`, a CI cancel or a supervisor stopping a process group: the signal goes
        # to the caller's group. The pool worker initializer installs the SIGTERM cleanup, so the worker ends its
        # command before it dies. With subprocess.run the test command shared that group and died with it.
        pid_file = tmp_path / 'command.pid'
        runner = (
            'import os, sys\n'
            'from pytest_gremlins.process_tree import install_sigterm_cleanup, run_bounded\n'
            'install_sigterm_cleanup()\n'
            f'run_bounded([sys.executable, "-c", {_sleeper_writing_pid(pid_file)!r}], cwd={str(tmp_path)!r},'
            f' env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})\n'
        )
        caller = subprocess.Popen(_python(runner), stderr=subprocess.DEVNULL, start_new_session=True)
        command = 0
        try:
            command = int(_wait_for_file(pid_file))
            os.killpg(caller.pid, signal.SIGTERM)
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            gone = _is_gone(command)
        finally:
            caller.kill()
            if command:
                _kill_quietly(command)

        assert gone

    def it_ends_a_command_run_from_a_worker_thread_on_a_terminal_interrupt(self, tmp_path: Path) -> None:
        # verdicts._confirm_collection_kills runs control runs in a ThreadPoolExecutor. A terminal Ctrl-C sends
        # SIGINT to the foreground group; only the main thread sees KeyboardInterrupt, so run_bounded in the
        # worker thread never cleans up. With subprocess.run the command got the SIGINT itself.
        pid_file = tmp_path / 'command.pid'
        runner = (
            'import os, sys, threading\n'
            'from pytest_gremlins.process_tree import run_bounded\n'
            'worker = threading.Thread(target=run_bounded, daemon=True,'
            f' args=([sys.executable, "-c", {_sleeper_writing_pid(pid_file)!r}],),'
            f' kwargs=dict(cwd={str(tmp_path)!r}, env=dict(os.environ), timeout={LONG_SLEEP_SECONDS}))\n'
            'worker.start()\n'
            'worker.join()\n'
        )
        caller = subprocess.Popen(_python(runner), stderr=subprocess.DEVNULL, start_new_session=True)
        command = 0
        try:
            command = int(_wait_for_file(pid_file))
            os.killpg(caller.pid, signal.SIGINT)
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            gone = _is_gone(command)
        finally:
            caller.kill()
            if command:
                _kill_quietly(command)

        assert gone

    def it_kills_a_sigterm_ignoring_command_when_interrupted_during_the_grace_period(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        fds_before = _open_fd_count()

        def interrupt(_signum: int, _frame: FrameType | None) -> None:
            raise KeyboardInterrupt

        previous = signal.signal(signal.SIGALRM, interrupt)
        signal.setitimer(signal.ITIMER_REAL, MID_GRACE_SECONDS)
        command = 0
        try:
            with pytest.raises(KeyboardInterrupt):
                _run(_python(_sleeper_writing_pid(pid_file, ignore_sigterm=True)), tmp_path, SHORT_TIMEOUT_SECONDS)
            command = int(_wait_for_file(pid_file))
            gone = _is_gone(command)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if command:
                _kill_quietly(command)

        assert (gone, _open_fd_count()) == (True, fds_before)


@pytest.mark.medium
@posix_only
class DescribeRunBoundedCost:
    def it_returns_promptly_when_the_command_exits_on_sigterm(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'

        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            _run(_python(_sleeper_writing_pid(pid_file)), tmp_path, SHORT_TIMEOUT_SECONDS)
        overhead = time.monotonic() - started - SHORT_TIMEOUT_SECONDS

        assert overhead < process_tree.TERMINATE_GRACE_SECONDS

    def it_leaves_no_file_descriptors_open_after_repeated_timeouts(self, tmp_path: Path) -> None:
        before = _open_fd_count()

        for _ in range(REPEATED_RUNS):
            with pytest.raises(subprocess.TimeoutExpired):
                _run(_python(f'import time; time.sleep({LONG_SLEEP_SECONDS})'), tmp_path, 0.05)

        assert _open_fd_count() == before

    def it_leaves_no_file_descriptors_open_after_a_missing_executable(self, tmp_path: Path) -> None:
        before = _open_fd_count()

        with pytest.raises(FileNotFoundError):
            _run([str(tmp_path / 'no-such-python')], tmp_path, SHORT_TIMEOUT_SECONDS)

        assert _open_fd_count() == before


@pytest.mark.medium
class DescribeRunBoundedLargeOutput:
    def it_returns_output_larger_than_a_pipe_buffer_intact(self, tmp_path: Path) -> None:
        code = f'import sys; sys.stdout.write("x" * {ONE_MEBIBYTE}); sys.stderr.write("y" * {ONE_MEBIBYTE})'

        completed = _run(_python(code), tmp_path, STARTUP_DEADLINE_SECONDS)

        assert (len(completed.stdout), len(completed.stderr)) == (ONE_MEBIBYTE, ONE_MEBIBYTE)

    def it_attaches_output_larger_than_a_pipe_buffer_to_the_timeout(self, tmp_path: Path) -> None:
        code = f'import sys, time; sys.stdout.write("x" * {ONE_MEBIBYTE}); sys.stdout.flush(); time.sleep(3600)'

        with pytest.raises(subprocess.TimeoutExpired) as expired:
            _run(_python(code), tmp_path, 2.0)

        assert len(expired.value.stdout or b'') == ONE_MEBIBYTE
