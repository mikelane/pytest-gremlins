"""Tests for the DEBUG traces run_bounded leaves when it has to end a timed-out test run (#975)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

from process_helpers import (  # type: ignore[import-not-found]
    STARTUP_DEADLINE_SECONDS,
    kill_quietly,
    python,
    wait_for_file,
)
import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

if TYPE_CHECKING:
    from pathlib import Path

LOGGER_NAME = 'pytest_gremlins.process_tree'
SHORT_TIMEOUT_SECONDS = 1
LONG_SLEEP_SECONDS = 3600
SHORT_DRAIN_SECONDS = 0.5

posix_only = pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')


def _run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return run_bounded(command, cwd=str(cwd), env=dict(os.environ), timeout=timeout)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]


def _messages_containing(caplog: pytest.LogCaptureFixture, *fragments: str) -> list[str]:
    return [message for message in _messages(caplog) if all(fragment in message for fragment in fragments)]


@pytest.mark.medium
@posix_only
class DescribeRunBoundedTimeoutTrace:
    def it_logs_the_timeout_and_the_exit_status_of_the_killed_command(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

        with pytest.raises(subprocess.TimeoutExpired):
            _run(python(f'import time; time.sleep({LONG_SLEEP_SECONDS})'), tmp_path, SHORT_TIMEOUT_SECONDS)

        assert (
            len(_messages_containing(caplog, f'outlasted {SHORT_TIMEOUT_SECONDS}s', f'exit status {-signal.SIGTERM}'))
            == 1
        )

    def it_logs_nothing_for_a_command_that_finishes_in_time(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

        _run(python('pass'), tmp_path, STARTUP_DEADLINE_SECONDS)

        assert _messages(caplog) == []

    def it_logs_that_a_process_outside_the_group_still_held_the_pipes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        pid_file = tmp_path / 'escaped.pid'
        code = (
            'import subprocess, sys, time\n'
            f'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({LONG_SLEEP_SECONDS})"],'
            ' start_new_session=True)\n'
            f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
            f'time.sleep({LONG_SLEEP_SECONDS})\n'
        )
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                _run(python(code), tmp_path, STARTUP_DEADLINE_SECONDS)
        finally:
            kill_quietly(int(wait_for_file(pid_file)))

        assert len(_messages_containing(caplog, 'still open', 'outside its group')) == 1
