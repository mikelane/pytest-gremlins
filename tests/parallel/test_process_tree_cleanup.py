"""The registry of live test commands and the signal cleanup built on it (#975)."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

REAP_DEADLINE_SECONDS = 10
POLL_SECONDS = 0.1
STARTUP_DEADLINE_SECONDS = 15
LONG_SLEEP_SECONDS = 3600
SHORT_TIMEOUT_SECONDS = 1.0

posix_only = pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')

_SLEEPER = 'import os, time; open({pid_file!r}, "w").write(str(os.getpid())); time.sleep({sleep})'


def _python(code: str) -> list[str]:
    return [sys.executable, '-c', code]


def _sleeper(pid_file: Path) -> list[str]:
    return _python(_SLEEPER.format(pid_file=str(pid_file), sleep=LONG_SLEEP_SECONDS))


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


def _spawn_caller(runner: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(_python(runner), stderr=subprocess.DEVNULL, start_new_session=True)


@pytest.mark.medium
@posix_only
class DescribeLiveCommandRegistry:
    def it_ends_a_running_command_from_another_thread_with_terminate_all(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        outcome: list[subprocess.CompletedProcess[bytes]] = []
        worker = threading.Thread(
            target=lambda: outcome.append(
                run_bounded(_sleeper(pid_file), cwd=str(tmp_path), env=dict(os.environ), timeout=LONG_SLEEP_SECONDS)
            ),
            daemon=True,
        )
        worker.start()
        command = int(_wait_for_file(pid_file))
        try:
            process_tree.terminate_all()
            worker.join(REAP_DEADLINE_SECONDS)
            gone = _is_gone(command)
        finally:
            _kill_quietly(command)

        assert (gone, worker.is_alive()) == (True, False)

    def it_forgets_a_command_once_it_has_finished(self, tmp_path: Path) -> None:
        run_bounded(_python('pass'), cwd=str(tmp_path), env=dict(os.environ), timeout=STARTUP_DEADLINE_SECONDS)

        assert process_tree.live_command_count() == 0

    def it_forgets_a_command_that_timed_out(self, tmp_path: Path) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            run_bounded(
                _python(f'import time; time.sleep({LONG_SLEEP_SECONDS})'),
                cwd=str(tmp_path),
                env=dict(os.environ),
                timeout=SHORT_TIMEOUT_SECONDS,
            )

        assert process_tree.live_command_count() == 0

    def it_does_nothing_when_no_command_is_running(self) -> None:
        process_tree.terminate_all()

        assert process_tree.live_command_count() == 0


@pytest.mark.small
class DescribeTerminateAllOnError:
    def it_ends_every_command_when_the_block_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ended: list[bool] = []
        monkeypatch.setattr(process_tree, 'terminate_all', lambda: ended.append(True))

        with pytest.raises(KeyboardInterrupt), process_tree.terminate_all_on_error():
            raise KeyboardInterrupt

        assert ended == [True]

    def it_leaves_commands_alone_when_the_block_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ended: list[bool] = []
        monkeypatch.setattr(process_tree, 'terminate_all', lambda: ended.append(True))

        with process_tree.terminate_all_on_error():
            pass

        assert ended == []


@pytest.mark.medium
@posix_only
class DescribeSigtermCleanup:
    def it_ends_the_command_and_dies_by_sigterm_when_the_main_process_is_terminated(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        runner = (
            'import os, sys\n'
            'from pytest_gremlins import process_tree\n'
            'with process_tree.sigterm_cleanup():\n'
            f'    process_tree.run_bounded({_sleeper(pid_file)!r}, cwd={str(tmp_path)!r},'
            f' env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})\n'
        )
        caller = _spawn_caller(runner)
        command = 0
        try:
            command = int(_wait_for_file(pid_file))
            os.killpg(caller.pid, signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            gone = _is_gone(command)
        finally:
            caller.kill()
            if command:
                _kill_quietly(command)

        assert (gone, returncode) == (True, -signal.SIGTERM)

    def it_runs_the_previous_sigterm_handler_after_the_cleanup(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        seen_file = tmp_path / 'previous.seen'
        runner = (
            'import os, signal, sys\n'
            'from pytest_gremlins import process_tree\n'
            f'def previous(signum, frame):\n    open({str(seen_file)!r}, "w").write("1")\n    sys.exit(0)\n'
            'signal.signal(signal.SIGTERM, previous)\n'
            'with process_tree.sigterm_cleanup():\n'
            f'    process_tree.run_bounded({_sleeper(pid_file)!r}, cwd={str(tmp_path)!r},'
            f' env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})\n'
        )
        caller = _spawn_caller(runner)
        command = 0
        try:
            command = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            gone = _is_gone(command)
        finally:
            caller.kill()
            if command:
                _kill_quietly(command)

        assert (gone, seen_file.exists()) == (True, True)

    def it_restores_the_previous_sigterm_handler_afterwards(self) -> None:
        before = signal.getsignal(signal.SIGTERM)

        with process_tree.sigterm_cleanup():
            during = signal.getsignal(signal.SIGTERM)

        assert (during is not before, signal.getsignal(signal.SIGTERM)) == (True, before)

    def it_leaves_the_handlers_alone_off_the_main_thread(self) -> None:
        before = signal.getsignal(signal.SIGTERM)
        seen: list[object] = []

        def enter() -> None:
            with process_tree.sigterm_cleanup():
                seen.append(signal.getsignal(signal.SIGTERM))

        worker = threading.Thread(target=enter)
        worker.start()
        worker.join()

        assert seen == [before]

    def it_does_not_touch_the_sigint_handler(self) -> None:
        before = signal.getsignal(signal.SIGINT)

        with process_tree.sigterm_cleanup():
            during = signal.getsignal(signal.SIGINT)

        assert during is before

    def it_only_ends_commands_started_by_this_process(self, tmp_path: Path) -> None:
        # A forked pool worker inherits the parent's registry; it must not kill the parent's commands.
        pid_file = tmp_path / 'command.pid'
        runner = (
            'import os, sys, threading, time\n'
            'from pytest_gremlins import process_tree\n'
            f'threading.Thread(target=process_tree.run_bounded, args=({_sleeper(pid_file)!r},), daemon=True,'
            f' kwargs=dict(cwd={str(tmp_path)!r}, env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})).start()\n'
            f'while not os.path.exists({str(pid_file)!r}):\n    time.sleep(0.05)\n'
            'child = os.fork()\n'
            'if child == 0:\n    process_tree.terminate_all()\n    os._exit(0)\n'
            'os.waitpid(child, 0)\n'
            f'open({str(tmp_path / "forked.done")!r}, "w").write("1")\n'
            'time.sleep(30)\n'
        )
        caller = _spawn_caller(runner)
        command = 0
        try:
            _wait_for_file(tmp_path / 'forked.done')
            command = int(_wait_for_file(pid_file))
            survived = not _is_gone_quickly(command)
        finally:
            caller.kill()
            caller.wait()
            if command:
                _kill_quietly(command)

        assert survived


def _is_gone_quickly(pid: int) -> bool:
    time.sleep(POLL_SECONDS * 5)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.medium
@posix_only
class DescribeSigtermCleanupLimits:
    def it_does_not_install_over_an_ignored_sigterm(self) -> None:
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            with process_tree.sigterm_cleanup():
                during = signal.getsignal(signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, previous)

        assert during == signal.SIG_IGN

    def it_does_not_install_the_worker_cleanup_over_an_ignored_sigterm(self) -> None:
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            process_tree.install_sigterm_cleanup()
            installed = signal.getsignal(signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, previous)

        assert installed == signal.SIG_IGN

    def it_leaves_a_running_command_alone_when_sigterm_is_ignored(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        runner = (
            'import os, signal, sys\n'
            'from pytest_gremlins import process_tree\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'with process_tree.sigterm_cleanup():\n'
            f'    process_tree.run_bounded({_sleeper(pid_file)!r}, cwd={str(tmp_path)!r},'
            f' env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})\n'
        )
        caller = _spawn_caller(runner)
        command = 0
        try:
            command = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            time.sleep(POLL_SECONDS * 10)
            still_running = caller.poll() is None and not _is_gone_quickly(command)
        finally:
            caller.kill()
            caller.wait()
            if command:
                _kill_quietly(command)

        assert still_running

    def it_terminates_multiprocessing_children_when_the_main_process_gets_sigterm(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'child.pid'
        runner = (
            'import multiprocessing, os, time\n'
            'from pytest_gremlins import process_tree\n'
            'def child():\n'
            '    process_tree.install_sigterm_cleanup()\n'
            f'    open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
            f'    time.sleep({LONG_SLEEP_SECONDS})\n'
            'if __name__ == "__main__":\n'
            "    worker = multiprocessing.get_context('fork').Process(target=child)\n"
            '    worker.start()\n'
            '    with process_tree.sigterm_cleanup():\n'
            f'        time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        caller = _spawn_caller(runner)
        worker = 0
        try:
            worker = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            gone = _is_gone(worker)
        finally:
            caller.kill()
            if worker:
                _kill_quietly(worker)

        assert (gone, returncode) == (True, -signal.SIGTERM)
