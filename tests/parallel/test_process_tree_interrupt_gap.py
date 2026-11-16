"""An interrupt that lands as the timeout is handled, before the grace period starts, still ends the command (#975).

CI evidence (run 43381312640, Test (Python 3.12, macos-latest)): the grace-period interrupt probe took 22.8s and left a
SIGTERM-ignoring command running ("subprocess N is still running"). The extra ~10s is the two PIPE_DRAIN_SECONDS waits
in ``_drain`` on a command that never got SIGKILL: the interrupt arrived after ``communicate`` raised TimeoutExpired
but before ``_terminate_tree`` reached its ``try``, so neither SIGTERM nor the ``finally`` SIGKILL ran.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

from process_helpers import (  # type: ignore[import-not-found]
    environment_without_coverage_hook,
    is_gone,
    kill_quietly,
    python,
    wait_for_file,
)
import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

TIMEOUT_SECONDS = 2.0
SHORT_DRAIN_SECONDS = 0.2


def _interrupted_on_entry(_process: object) -> None:
    raise KeyboardInterrupt


def _sleeper_ignoring_sigterm(pid_file: Path) -> str:
    return (
        'import os, signal, time\n'
        'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
        'time.sleep(3600)\n'
    )


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')
class DescribeRunBoundedInterruptedAsTheTimeoutIsHandled:
    def it_ends_a_sigterm_ignoring_command_when_interrupted_before_the_grace_period(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_file = tmp_path / 'command.pid'
        sleeper = _sleeper_ignoring_sigterm(pid_file)
        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_terminate_tree', _interrupted_on_entry)
        command_pid = 0
        try:
            with pytest.raises(KeyboardInterrupt):
                run_bounded(
                    python(sleeper), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=TIMEOUT_SECONDS
                )
            command_pid = int(wait_for_file(pid_file))
            is_command_gone = is_gone(command_pid)
        finally:
            kill_quietly(command_pid)

        assert is_command_gone

    def it_ends_a_command_when_interrupted_while_it_is_being_registered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[int] = []
        real_start = process_tree._start

        def recording_start(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = real_start(*args, **kwargs)
            started.append(process.pid)
            return process

        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_start', recording_start)
        monkeypatch.setattr(process_tree, '_register', _interrupted_on_entry)
        try:
            with pytest.raises(KeyboardInterrupt):
                run_bounded(
                    python(_sleeper_ignoring_sigterm(tmp_path / 'command.pid')),
                    cwd=str(tmp_path),
                    env=environment_without_coverage_hook(),
                    timeout=TIMEOUT_SECONDS,
                )
            is_command_gone = is_gone(started[0])
        finally:
            for pid in started:
                kill_quietly(pid)

        assert is_command_gone
