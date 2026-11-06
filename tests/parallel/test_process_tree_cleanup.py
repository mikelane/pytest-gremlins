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
    if pid <= 0:  # 0 means "never started"; os.kill(0, ...) would signal this test's own process group
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


def _wait_for_live_commands(count: int) -> None:
    # The command can write its pid file before run_bounded has registered it.
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if process_tree.live_command_count() == count:
            return
        time.sleep(POLL_SECONDS)
    msg = f'{count} live command(s) never registered'
    raise AssertionError(msg)


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
        command_pid = int(_wait_for_file(pid_file))
        try:
            process_tree.terminate_all()
            worker.join(REAP_DEADLINE_SECONDS)
            is_command_gone = _is_gone(command_pid)
        finally:
            _kill_quietly(command_pid)

        assert (is_command_gone, worker.is_alive()) == (True, False)

    def it_neither_counts_nor_ends_a_command_owned_by_another_process(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pins the owner check itself; the fork test below also passes on the at-fork registry reset alone.
        pid_file = tmp_path / 'command.pid'
        worker = threading.Thread(
            target=run_bounded,
            args=(_sleeper(pid_file),),
            kwargs={'cwd': str(tmp_path), 'env': dict(os.environ), 'timeout': LONG_SLEEP_SECONDS},
            daemon=True,
        )
        worker.start()
        command_pid = 0
        own_pid = os.getpid()
        try:
            command_pid = int(_wait_for_file(pid_file))
            _wait_for_live_commands(1)
            monkeypatch.setattr(os, 'getpid', lambda: own_pid + 1)
            count_seen_by_other = process_tree.live_command_count()
            process_tree.terminate_all()
            monkeypatch.undo()
            is_command_alive = not _is_gone_quickly(command_pid)
        finally:
            monkeypatch.undo()
            process_tree.terminate_all()
            worker.join(REAP_DEADLINE_SECONDS)
            _kill_quietly(command_pid)

        assert (count_seen_by_other, is_command_alive) == (0, True)

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
        command_pid = 0
        try:
            command_pid = int(_wait_for_file(pid_file))
            os.killpg(caller.pid, signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = _is_gone(command_pid)
        finally:
            caller.kill()
            if command_pid:
                _kill_quietly(command_pid)

        assert (is_command_gone, returncode) == (True, -signal.SIGTERM)

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
        command_pid = 0
        try:
            command_pid = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = _is_gone(command_pid)
        finally:
            caller.kill()
            if command_pid:
                _kill_quietly(command_pid)

        # Exit status 0 is the previous handler's sys.exit(0): the cleanup did not also re-raise SIGTERM after it.
        assert (is_command_gone, seen_file.exists(), returncode) == (True, True, 0)

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
        worker.join(REAP_DEADLINE_SECONDS)

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
        command_pid = 0
        try:
            _wait_for_file(tmp_path / 'forked.done')
            command_pid = int(_wait_for_file(pid_file))
            has_survived = not _is_gone_quickly(command_pid)
        finally:
            caller.kill()
            caller.wait(timeout=REAP_DEADLINE_SECONDS)
            if command_pid:
                _kill_quietly(command_pid)

        assert has_survived


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
        command_pid = 0
        try:
            command_pid = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            time.sleep(POLL_SECONDS * 10)
            is_still_running = caller.poll() is None and not _is_gone_quickly(command_pid)
        finally:
            caller.kill()
            caller.wait(timeout=REAP_DEADLINE_SECONDS)
            if command_pid:
                _kill_quietly(command_pid)

        assert is_still_running

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
        worker_pid = 0
        try:
            worker_pid = int(_wait_for_file(pid_file))
            caller.send_signal(signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_worker_gone = _is_gone(worker_pid)
        finally:
            caller.kill()
            if worker_pid:
                _kill_quietly(worker_pid)

        assert (is_worker_gone, returncode) == (True, -signal.SIGTERM)

    def it_stops_waiting_for_workers_that_ignore_sigterm_after_the_worker_stop_deadline(self, tmp_path: Path) -> None:
        # Two workers ignore SIGTERM, so each join runs out. WORKER_STOP_SECONDS bounds the wait in total: an
        # unbounded join hangs the main process forever, and a per-worker bound doubles it.
        pid_files = (tmp_path / 'first.pid', tmp_path / 'second.pid')
        runner = (
            'import multiprocessing, os, signal, sys, time\n'
            'from pytest_gremlins import process_tree\n'
            'def child(pid_file):\n'
            '    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            '    open(pid_file, "w").write(str(os.getpid()))\n'
            f'    time.sleep({LONG_SLEEP_SECONDS})\n'
            'if __name__ == "__main__":\n'
            "    context = multiprocessing.get_context('fork')\n"
            f'    context.Process(target=child, args=({str(pid_files[0])!r},)).start()\n'
            f'    context.Process(target=child, args=({str(pid_files[1])!r},)).start()\n'
            '    with process_tree.sigterm_cleanup():\n'
            f'        time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        caller = _spawn_caller(runner)
        worker_pids = [0, 0]
        try:
            worker_pids = [int(_wait_for_file(pid_files[0])), int(_wait_for_file(pid_files[1]))]
            started = time.monotonic()
            caller.send_signal(signal.SIGTERM)
            returncode = caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            elapsed = time.monotonic() - started
        finally:
            caller.kill()
            _kill_quietly(worker_pids[0])
            _kill_quietly(worker_pids[1])

        assert (returncode, elapsed < 2 * process_tree.WORKER_STOP_SECONDS) == (-signal.SIGTERM, True)
