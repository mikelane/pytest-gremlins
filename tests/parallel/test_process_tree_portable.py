"""Tests for the process_tree paths that run on every platform, with fakes in place of real commands (#975).

The real-command tests are POSIX-only (process groups and signals), so Windows would not otherwise execute these paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import cast

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


def as_popen(process: FakeProcess) -> subprocess.Popen[bytes]:
    return cast('subprocess.Popen[bytes]', process)


class FakePipe:
    def __init__(self) -> None:
        self.is_closed = False

    def close(self) -> None:
        self.is_closed = True


@pytest.mark.small
class DescribeWaitForInterrupt:
    def it_ends_the_tree_and_reraises_when_the_wait_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ended: list[object] = []
        drained: list[object] = []

        def record_drain(process: object) -> tuple[bytes, bytes]:
            drained.append(process)
            return b'', b''

        monkeypatch.setattr(process_tree, '_kill_tree', ended.append)
        monkeypatch.setattr(process_tree, '_drain', record_drain)
        process = FakeProcess(communicate_error=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            process_tree._wait_for(as_popen(process), ['cmd'], 1.0)

        assert ended == [process]
        assert drained == [process]


@pytest.mark.small
class DescribeDrain:
    def it_returns_what_the_command_wrote(self) -> None:
        assert process_tree._drain(as_popen(FakeProcess())) == (b'out', b'err')

    def it_returns_partial_output_when_an_outsider_holds_the_pipes_open(self) -> None:
        still_open = subprocess.TimeoutExpired(['cmd'], 1.0, output=b'partial', stderr=None)
        process = FakeProcess(communicate_error=still_open)

        output = process_tree._drain(as_popen(process))

        assert output == (b'partial', b'')

    @pytest.mark.skipif(sys.platform == 'win32', reason='only POSIX closes the pipes of the abandoned command')
    def it_closes_the_pipes_it_gave_up_on(self) -> None:
        process = FakeProcess(communicate_error=subprocess.TimeoutExpired(['cmd'], 1.0))

        process_tree._drain(as_popen(process))

        assert (process.stdout.is_closed, process.stderr.is_closed) == (True, True)


@pytest.mark.small
class DescribeTaskkillTree:
    @pytest.mark.parametrize(
        'failure',
        [OSError('taskkill is missing'), subprocess.TimeoutExpired(['taskkill'], 10)],
        ids=['cannot-run', 'times-out'],
    )
    def it_falls_back_to_killing_the_process_when_taskkill_fails(
        self, monkeypatch: pytest.MonkeyPatch, failure: BaseException
    ) -> None:
        def failing_run(*_args: object, **_kwargs: object) -> None:
            raise failure

        monkeypatch.setattr('pytest_gremlins.process_tree.subprocess.run', failing_run)
        process = FakeProcess()

        process_tree._taskkill_tree(as_popen(process))

        assert process.was_killed is True

    def it_ends_the_tree_with_taskkill_when_it_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []

        def recording_run(command: list[str], **_kwargs: object) -> None:
            commands.append(command)

        monkeypatch.setattr('pytest_gremlins.process_tree.subprocess.run', recording_run)
        process = FakeProcess()

        process_tree._taskkill_tree(as_popen(process))

        assert [command[1:] for command in commands] == [['/F', '/T', '/PID', str(FAKE_PID)]]
        assert process.was_killed is False


@pytest.mark.small
class DescribeRegistry:
    def it_reports_no_live_commands_when_none_are_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_tree, '_live_commands', {})

        assert process_tree.live_command_count() == 0

    def it_reports_no_watchdog_before_one_was_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(process_tree, '_watchdog', None)

        assert process_tree.watchdog_pid() is None

    def it_ends_every_registered_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first, second = FakeProcess(), FakeProcess()
        monkeypatch.setattr(
            process_tree, '_live_commands', {FAKE_PID: (os.getpid(), first), FAKE_PID + 1: (os.getpid(), second)}
        )
        ended: list[object] = []
        monkeypatch.setattr(process_tree, '_kill_tree', ended.append)

        process_tree.kill_live_commands()

        assert ended == [first, second]

    def it_leaves_commands_started_by_another_process_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        inherited = FakeProcess()
        monkeypatch.setattr(process_tree, '_live_commands', {FAKE_PID: (os.getpid() + 1, inherited)})
        ended: list[object] = []
        monkeypatch.setattr(process_tree, '_kill_tree', ended.append)

        process_tree.kill_live_commands()

        assert ended == []
