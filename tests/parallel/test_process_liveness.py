"""The shared liveness probe must not signal the process on Windows, where ``os.kill`` is not a probe."""

from __future__ import annotations

import os

import pytest

from tests import process_liveness


@pytest.mark.small
class DescribeIsAlive:
    def it_reports_this_process_as_alive(self) -> None:
        assert process_liveness.is_alive(os.getpid())

    def it_asks_the_windows_probe_and_never_calls_os_kill_on_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # os.kill(pid, 0) is GenerateConsoleCtrlEvent there, and any other signal ends the process.
        def refuse_kill(_pid: int, _signal: int) -> None:
            pytest.fail('is_alive called os.kill on Windows')

        monkeypatch.setattr(process_liveness, '_IS_WINDOWS', True)
        monkeypatch.setattr(process_liveness, '_windows_process_is_running', lambda pid: pid == 4242)
        monkeypatch.setattr(os, 'kill', refuse_kill)

        assert process_liveness.is_alive(4242)
        assert not process_liveness.is_alive(1)
