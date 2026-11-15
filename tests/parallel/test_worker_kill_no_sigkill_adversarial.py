"""Adversarial QA run 5 (#976): killing workers by pid on a platform with no SIGKILL (Windows).

Before 0cfb338 the pool's own ``_sigkill`` sent ``getattr(signal, 'SIGKILL', signal.SIGTERM)``, so on Windows it
fell back to SIGTERM (``TerminateProcess``). The move to ``worker_kill.sigkill_pids`` sends ``signal.SIGKILL``,
which Windows does not define: the call raises AttributeError before any pid is signalled. ``_abandon_workers``
then skips its direct kill and ``executor.shutdown(wait=False, cancel_futures=True)``, and ``__exit__`` logs
"Cannot kill the pool workers" on every error exit on Windows.
"""

from __future__ import annotations

import os
import signal
from types import SimpleNamespace

import pytest

from pytest_gremlins.parallel import worker_kill


@pytest.fixture
def platform_without_sigkill(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    sent: list[tuple[int, int]] = []

    def recording_kill(pid: int, signal_number: int) -> None:
        sent.append((pid, signal_number))

    monkeypatch.setattr(worker_kill, 'signal', SimpleNamespace(SIGTERM=signal.SIGTERM))
    monkeypatch.setattr(os, 'kill', recording_kill)
    return sent


@pytest.mark.small
class DescribeSigkillPidsWithoutSigkill:
    def it_signals_every_pid_when_the_platform_has_no_sigkill(
        self, platform_without_sigkill: list[tuple[int, int]]
    ) -> None:
        worker_kill.sigkill_pids([101, 102])

        assert platform_without_sigkill == [(101, signal.SIGTERM), (102, signal.SIGTERM)]

    def it_signals_the_descendants_when_the_platform_has_no_sigkill(
        self, platform_without_sigkill: list[tuple[int, int]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda _root: [201])

        worker_kill.kill_children_of([200])

        assert platform_without_sigkill == [(201, signal.SIGTERM)]
