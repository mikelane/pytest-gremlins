"""Adversarial probes of the watchdog helper that ends test commands when their caller dies (#975, QA run 5)."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from process_helpers import (  # type: ignore[import-not-found]
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
    pytest.mark.skipif(sys.platform == 'win32', reason='the watchdog, fork and SIGKILL are POSIX'),
]

_RUN_ONE_COMMAND = (
    'import os, signal, sys, time\n'
    'from pytest_gremlins import process_tree\n'
    'process_tree.run_bounded([sys.executable, "-c", "pass"], cwd=os.getcwd(), env=dict(os.environ), timeout=30)\n'
)


class DescribeWatchdogAfterFork:
    def it_writes_nothing_to_stderr_in_a_child_forked_after_a_command_ran(self) -> None:
        # A Linux pool on Python 3.11-3.13 forks its workers (ProcessPoolExecutor's default context) after the main
        # process ran the pre-scan and the control run through run_bounded.
        runner = f'{_RUN_ONE_COMMAND}child = os.fork()\nif child == 0:\n    os._exit(0)\nos.waitpid(child, 0)\n'

        completed = subprocess.run(python(runner), capture_output=True, check=False, timeout=STARTUP_DEADLINE_SECONDS)

        assert (completed.returncode, completed.stderr) == (0, b'')

    def it_warns_of_nothing_in_development_mode_in_a_forked_child_that_drops_the_watchdog(self) -> None:
        # The forked child inherits the watchdog's Popen but is not its parent, so it must not warn "still running".
        runner = f'{_RUN_ONE_COMMAND}child = os.fork()\nif child == 0:\n    os._exit(0)\nos.waitpid(child, 0)\n'

        completed = subprocess.run(
            [sys.executable, '-X', 'dev', '-W', 'error::ResourceWarning', '-c', runner],
            capture_output=True,
            check=False,
            timeout=STARTUP_DEADLINE_SECONDS,
        )

        assert (completed.returncode, completed.stderr) == (0, b'')


class DescribeWatchdogThatDied:
    @pytest.mark.xfail(
        strict=True,
        reason='QA run 5: a dead watchdog is never replaced, so commands started afterwards are unprotected',
    )
    def it_ends_a_later_command_when_the_caller_is_sigkilled_after_its_first_watchdog_died(
        self, tmp_path: Path
    ) -> None:
        command_script = tmp_path / 'command.py'
        command_script.write_text(
            f'import os, time\nopen({str(tmp_path / "command.pid")!r}, "w").write(str(os.getpid()))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        caller_source = (
            f'{_RUN_ONE_COMMAND}'
            'import threading\n'
            'first = process_tree.watchdog_pid()\n'
            'os.kill(first, signal.SIGKILL)\n'
            'os.waitpid(first, 0)\n'
            f'command = [sys.executable, {str(command_script)!r}]\n'
            'threading.Thread(target=process_tree.run_bounded, args=(command,), daemon=True,'
            f' kwargs=dict(cwd=os.getcwd(), env=dict(os.environ), timeout={LONG_SLEEP_SECONDS})).start()\n'
            'while process_tree.live_command_count() == 0:\n'
            '    time.sleep(0.05)\n'
            f'open({str(tmp_path / "caller.ready")!r}, "w").write("ready")\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        caller = subprocess.Popen(python(caller_source), stderr=subprocess.DEVNULL, start_new_session=True)
        command_pid = 0
        try:
            command_pid = int(wait_for_file(tmp_path / 'command.pid'))
            wait_for_file(tmp_path / 'caller.ready')
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_command_gone = is_gone(command_pid)
        finally:
            caller.kill()
            caller.wait(timeout=STARTUP_DEADLINE_SECONDS)
            kill_quietly(command_pid)
            # The replacement watchdog, if any, exits on its own once the caller is gone.

        assert is_command_gone

    @pytest.mark.xfail(
        strict=True,
        reason='QA run 5: with SIGPIPE at its default action, telling a dead watchdog kills the caller by SIGPIPE',
    )
    def it_keeps_running_commands_when_the_watchdog_died_and_sigpipe_is_default(self) -> None:
        # Some CLIs and plugins restore SIGPIPE to SIG_DFL to avoid BrokenPipeError tracebacks.
        runner = (
            'import os, signal, sys\n'
            'signal.signal(signal.SIGPIPE, signal.SIG_DFL)\n'
            f'{_RUN_ONE_COMMAND}'
            'watchdog = process_tree.watchdog_pid()\n'
            'os.kill(watchdog, signal.SIGKILL)\n'
            'os.waitpid(watchdog, 0)\n'
            'process_tree.run_bounded([sys.executable, "-c", "pass"], cwd=os.getcwd(), env=dict(os.environ),'
            ' timeout=30)\n'
        )

        completed = subprocess.run(python(runner), capture_output=True, check=False, timeout=STARTUP_DEADLINE_SECONDS)

        assert completed.returncode == 0
