"""Tests for run_bounded, which ends a timed-out test run's whole process tree (#975)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from process_helpers import (  # type: ignore[import-not-found]
    REAP_DEADLINE_SECONDS,
    STARTUP_DEADLINE_SECONDS,
    is_gone,
    kill_quietly,
    python,
    wait_for_file,
)
import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

if TYPE_CHECKING:
    from pathlib import Path

SHORT_TIMEOUT_SECONDS = 1
LONG_SLEEP_SECONDS = 3600
SHORT_DRAIN_SECONDS = 0.5

posix_only = pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')


def _run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return run_bounded(command, cwd=str(cwd), env=dict(os.environ), timeout=timeout)


@pytest.mark.medium
class DescribeRunBounded:
    def it_returns_the_exit_code_and_both_output_streams(self, tmp_path: Path) -> None:
        code = 'import sys; print("out"); print("err", file=sys.stderr); sys.exit(3)'

        completed = _run(python(code), tmp_path, timeout=STARTUP_DEADLINE_SECONDS)

        assert (completed.returncode, completed.stdout.strip(), completed.stderr.strip()) == (3, b'out', b'err')

    def it_runs_the_command_in_the_given_directory_and_environment(self, tmp_path: Path) -> None:
        code = 'import os; print(os.getcwd()); print(os.environ["GREMLIN_PROBE"])'

        completed = run_bounded(
            python(code),
            cwd=str(tmp_path),
            env={**os.environ, 'GREMLIN_PROBE': 'x'},
            timeout=STARTUP_DEADLINE_SECONDS,
        )

        assert completed.stdout.split() == [str(tmp_path.resolve()).encode(), b'x']

    def it_raises_timeout_expired_with_the_output_written_before_the_kill(self, tmp_path: Path) -> None:
        code = f'import time; print("partial", flush=True); time.sleep({LONG_SLEEP_SECONDS})'

        with pytest.raises(subprocess.TimeoutExpired) as expired:
            _run(python(code), tmp_path, SHORT_TIMEOUT_SECONDS)

        assert (expired.value.stdout or b'').strip() == b'partial'

    @posix_only
    def it_kills_a_grandchild_that_outlives_the_timed_out_command(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'grandchild.pid'
        code = (
            'import subprocess, sys, time\n'
            f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({LONG_SLEEP_SECONDS})"])\n'
            f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        with pytest.raises(subprocess.TimeoutExpired):
            _run(python(code), tmp_path, STARTUP_DEADLINE_SECONDS)
        grandchild_pid = int(pid_file.read_text())
        try:
            is_grandchild_gone = is_gone(grandchild_pid)
        finally:
            kill_quietly(grandchild_pid)

        assert is_grandchild_gone

    @posix_only
    def it_force_kills_a_command_that_ignores_sigterm(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'command.pid'
        code = (
            'import os, signal, time\n'
            'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )

        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            _run(python(code), tmp_path, STARTUP_DEADLINE_SECONDS)
        elapsed = time.monotonic() - started - STARTUP_DEADLINE_SECONDS  # the part past the timeout
        command_pid = int(pid_file.read_text())
        try:
            is_command_gone = is_gone(command_pid)
        finally:
            kill_quietly(command_pid)

        assert (is_command_gone, elapsed < REAP_DEADLINE_SECONDS) == (True, True)

    @posix_only
    def it_sends_sigterm_before_the_force_kill(self, tmp_path: Path) -> None:
        # A command that handles SIGTERM gets to run its handler; a bare SIGKILL would leave no marker.
        marker = tmp_path / 'sigterm.seen'
        code = (
            'import signal, sys, time\n'
            f'def on_sigterm(signum, frame):\n    open({str(marker)!r}, "w").write("1")\n    sys.exit(0)\n'
            'signal.signal(signal.SIGTERM, on_sigterm)\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )

        with pytest.raises(subprocess.TimeoutExpired):
            _run(python(code), tmp_path, STARTUP_DEADLINE_SECONDS)

        assert marker.read_text() == '1'

    @posix_only
    def it_stops_waiting_for_pipes_held_by_a_process_that_left_the_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        pid_file = tmp_path / 'escaped.pid'
        code = (
            'import subprocess, sys, time\n'
            f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({LONG_SLEEP_SECONDS})"],'
            ' start_new_session=True)\n'
            f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        started = time.monotonic()
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                _run(python(code), tmp_path, STARTUP_DEADLINE_SECONDS)
            elapsed = time.monotonic() - started - STARTUP_DEADLINE_SECONDS  # the part past the timeout
        finally:
            kill_quietly(int(pid_file.read_text()))

        assert elapsed < REAP_DEADLINE_SECONDS


@pytest.mark.medium
@posix_only
class DescribeRunBoundedInterrupt:
    def it_kills_the_command_tree_when_the_run_is_interrupted(self, tmp_path: Path) -> None:
        pid_file = tmp_path / 'grandchild.pid'
        inner = (
            'import subprocess, sys, time\n'
            f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({LONG_SLEEP_SECONDS})"])\n'
            f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        runner = (
            'import os, sys\n'
            'from pytest_gremlins.process_tree import run_bounded\n'
            f'run_bounded([sys.executable, "-c", {inner!r}], cwd={str(tmp_path)!r}, env=dict(os.environ),'
            f' timeout={LONG_SLEEP_SECONDS})\n'
        )
        gremlins_run = subprocess.Popen(python(runner), stderr=subprocess.DEVNULL)
        grandchild_pid = 0
        try:
            grandchild_pid = int(wait_for_file(pid_file))
            gremlins_run.send_signal(signal.SIGINT)
            gremlins_run.wait(timeout=STARTUP_DEADLINE_SECONDS)
            is_grandchild_gone = is_gone(grandchild_pid)
        finally:
            gremlins_run.kill()
            kill_quietly(grandchild_pid)

        assert is_grandchild_gone
