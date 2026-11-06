"""Helpers for tests that start real processes and check what became of them (#975).

Imported by name (``pythonpath = ["tests"]``), like the other shared test modules.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import time

POLL_SECONDS = 0.1
STARTUP_DEADLINE_SECONDS = 15
"""How long a started process may take to reach a point it reports, under CI load."""
REAP_DEADLINE_SECONDS = 10
"""How long a killed process may take to disappear."""

_FORCE_KILL = getattr(signal, 'SIGKILL', signal.SIGTERM)


def python(code: str) -> list[str]:
    """Return the command line that runs ``code`` in this interpreter."""
    return [sys.executable, '-c', code]


def wait_for_file(path: Path) -> str:
    """Return the text of ``path`` once it is non-empty, failing after ``STARTUP_DEADLINE_SECONDS``."""
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(POLL_SECONDS)
    msg = f'{path} was not written'
    raise AssertionError(msg)


def wait_for_pid(path: Path) -> int:
    """Return the pid a process wrote to ``path``."""
    return int(wait_for_file(path))


def is_gone(pid: int) -> bool:
    """Return whether the process disappears within ``REAP_DEADLINE_SECONDS`` (POSIX)."""
    deadline = time.monotonic() + REAP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(POLL_SECONDS)
    return False


def survives_for(pid: int, seconds: float) -> bool:
    """Return whether the process is still alive after ``seconds`` (POSIX); polls, so an early exit ends it."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(POLL_SECONDS)
    return True


def kill_quietly(pid: int) -> None:
    """Force-kill ``pid`` if it is still there; ``0`` means "never started" and is ignored."""
    if pid <= 0:  # os.kill(0, ...) would signal this test's own process group
        return
    try:
        os.kill(pid, _FORCE_KILL)
    except (ProcessLookupError, PermissionError):
        return
