"""Adversarial QA probes (#975 rerun): interrupts at the edges of run_bounded's protected scope."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

from process_helpers import (  # type: ignore[import-not-found]
    environment_without_coverage_hook,
    is_gone,
    kill_quietly,
    python,
)
import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.process_tree import run_bounded

TIMEOUT_SECONDS = 2.0
SHORT_DRAIN_SECONDS = 0.2
SLEEPER = 'import time\ntime.sleep(3600)\n'


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')
class DescribeRunBoundedInterruptedAsTheCommandStarts:
    def it_ends_a_command_when_the_interrupt_lands_after_the_child_was_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[subprocess.Popen[bytes]] = []
        real_start = process_tree._start

        def start_then_interrupted(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = real_start(*args, **kwargs)
            started.append(process)
            os.kill(os.getpid(), signal.SIGINT)  # a real Ctrl-C arriving as the child is created
            return process

        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_start', start_then_interrupted)
        try:
            with pytest.raises(KeyboardInterrupt):
                run_bounded(
                    python(SLEEPER), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=TIMEOUT_SECONDS
                )
            is_command_gone = is_gone(started[0].pid)
        finally:
            for process in started:
                kill_quietly(process.pid)
                process.communicate()

        assert is_command_gone


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')
class DescribeRunBoundedInterruptedAfterTheTimeoutDrain:
    def it_raises_the_interrupt_and_leaves_no_registry_entry_when_it_lands_after_the_drain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_drain = process_tree._drain
        calls: list[int] = []

        def drain_then_interrupted(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
            calls.append(process.pid)
            result = real_drain(process)
            if len(calls) == 1:
                raise KeyboardInterrupt
            return result

        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_drain', drain_then_interrupted)
        with pytest.raises(KeyboardInterrupt):
            run_bounded(python(SLEEPER), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=0.5)

        assert (len(calls), process_tree.live_command_count(), is_gone(calls[0])) == (2, 0, True)


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')
class DescribeRunBoundedInterruptedDuringTheTimeoutDrain:
    def it_raises_the_interrupt_after_draining_abandoned_pipes_a_second_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[subprocess.Popen[bytes]] = []
        calls: list[int] = []
        real_start = process_tree._start

        def start_with_interrupted_drain(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = real_start(*args, **kwargs)
            real_communicate = process.communicate

            def communicate(*c_args: Any, **c_kwargs: Any) -> tuple[bytes, bytes]:
                calls.append(1)
                if len(calls) == 2:
                    raise KeyboardInterrupt
                return real_communicate(*c_args, **c_kwargs)

            process.communicate = communicate  # type: ignore[method-assign]
            started.append(process)
            return process

        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_start', start_with_interrupted_drain)
        with pytest.raises(KeyboardInterrupt):
            run_bounded(python(SLEEPER), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=0.5)

        assert (len(calls), started[0].returncode is not None, process_tree.live_command_count()) == (3, True, 0)


MASK_AND_HANDLERS_PROBE = (
    'import signal\n'
    'blocked = signal.pthread_sigmask(signal.SIG_BLOCK, [])\n'
    'print(signal.SIGINT in blocked, signal.SIGTERM in blocked,\n'
    '      signal.getsignal(signal.SIGINT) == signal.default_int_handler,\n'
    '      signal.getsignal(signal.SIGTERM) == signal.SIG_DFL)\n'
)


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='process groups and signals are POSIX')
class DescribeRunBoundedDeferringInterruptsWhileStarting:
    def it_starts_the_command_with_no_blocked_signals_and_default_handlers(self, tmp_path: Path) -> None:
        result = run_bounded(
            python(MASK_AND_HANDLERS_PROBE), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=10
        )

        assert result.stdout.split() == [b'False', b'False', b'True', b'True']

    def it_restores_the_callers_signal_handlers_afterwards(self, tmp_path: Path) -> None:
        def caller_handler(_signum: int, _frame: object) -> None:
            pass

        previous = signal.signal(signal.SIGTERM, caller_handler)
        try:
            run_bounded(python('pass'), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=10)
            restored = signal.getsignal(signal.SIGTERM)
        finally:
            signal.signal(signal.SIGTERM, previous)

        assert restored is caller_handler

    def it_delivers_a_sigterm_that_landed_during_the_start_to_the_callers_handler_and_ends_the_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started: list[subprocess.Popen[bytes]] = []
        real_start = process_tree._start

        def raise_terminated(signum: int, _frame: object) -> None:
            raise SystemExit(signum)

        def start_then_terminated(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            process = real_start(*args, **kwargs)
            started.append(process)
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        monkeypatch.setattr(process_tree, 'PIPE_DRAIN_SECONDS', SHORT_DRAIN_SECONDS)
        monkeypatch.setattr(process_tree, '_start', start_then_terminated)
        previous = signal.signal(signal.SIGTERM, raise_terminated)
        try:
            with pytest.raises(SystemExit) as raised:
                run_bounded(
                    python(SLEEPER), cwd=str(tmp_path), env=environment_without_coverage_hook(), timeout=TIMEOUT_SECONDS
                )
            is_command_gone = is_gone(started[0].pid)
        finally:
            signal.signal(signal.SIGTERM, previous)
            for process in started:
                kill_quietly(process.pid)
                process.communicate()

        assert (raised.value.code, is_command_gone) == (signal.SIGTERM, True)
