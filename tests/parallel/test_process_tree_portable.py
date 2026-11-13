"""Tests for the process_tree paths that run on every platform, with fakes in place of real commands (#975).

The real-command tests are POSIX-only (process groups and signals), so Windows would not otherwise execute these paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from pytest_gremlins import process_tree

FAKE_PID = 4242
FAKE_EXIT_STATUS = 7


class FakeProcess:
    """A stand-in for a ``Popen`` that records what was done to it."""

    def __init__(self, communicate_error: BaseException | None = None) -> None:
        self.pid = FAKE_PID
        self.returncode = FAKE_EXIT_STATUS
        self.stdout = FakePipe()
        self.stderr = FakePipe()
        self.was_killed = False
        self._communicate_error = communicate_error

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:  # noqa: ARG002 - Popen's signature
        if self._communicate_error is not None:
            raise self._communicate_error
        return b'out', b'err'

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002 - Popen's signature
        return self.returncode

    def kill(self) -> None:
        self.was_killed = True


class FakePipe:
    def __init__(self) -> None:
        self.is_closed = False

    def close(self) -> None:
        self.is_closed = True


@pytest.mark.small
class DescribeWaitForInterrupt:
    def it_ends_the_tree_and_reraises_when_the_wait_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ended: list[Any] = []
        monkeypatch.setattr(process_tree, '_kill_tree', ended.append)
        monkeypatch.setattr(process_tree, '_drain', lambda _process: (b'', b''))
        process = FakeProcess(communicate_error=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            process_tree._wait_for(process, ['cmd'], 1.0)  # type: ignore[arg-type]

        assert ended == [process]


@pytest.mark.small
class DescribeDrain:
    def it_returns_what_the_command_wrote(self) -> None:
        assert process_tree._drain(FakeProcess()) == (b'out', b'err')  # type: ignore[arg-type]

    def it_returns_partial_output_and_closes_pipes_held_open_by_an_outsider(self) -> None:
        still_open = subprocess.TimeoutExpired(['cmd'], 1.0, output=b'partial', stderr=None)
        process = FakeProcess(communicate_error=still_open)

        output = process_tree._drain(process)  # type: ignore[arg-type]

        assert output == (b'partial', b'')

    @pytest.mark.skipif(sys.platform == 'win32', reason='only POSIX closes the pipes of the abandoned command')
    def it_closes_the_pipes_it_gave_up_on(self) -> None:
        process = FakeProcess(communicate_error=subprocess.TimeoutExpired(['cmd'], 1.0))

        process_tree._drain(process)  # type: ignore[arg-type]

        assert process.stdout.is_closed is True


@pytest.mark.small
class DescribeTaskkillTree:
    def it_falls_back_to_killing_the_process_when_taskkill_cannot_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unavailable(*_args: object, **_kwargs: object) -> None:
            raise OSError('taskkill is missing')

        monkeypatch.setattr(
            process_tree, 'subprocess', SimpleNamespace(run=unavailable, TimeoutExpired=subprocess.TimeoutExpired)
        )
        process = FakeProcess()

        process_tree._taskkill_tree(process)  # type: ignore[arg-type]

        assert process.was_killed is True


@pytest.mark.small
class DescribeRegistry:
    def it_reports_no_live_commands_when_none_are_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_tree, '_live_commands', {})

        assert process_tree.live_command_count() == 0

    def it_reports_no_watchdog_before_one_was_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_tree, '_watchdog', None)

        assert process_tree.watchdog_pid() is None

    def it_ends_every_registered_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        process = FakeProcess()
        monkeypatch.setattr(process_tree, '_live_commands', {FAKE_PID: (os.getpid(), process)})
        ended: list[Any] = []
        monkeypatch.setattr(process_tree, '_kill_tree', ended.append)

        process_tree.kill_live_commands()

        assert ended == [process]
