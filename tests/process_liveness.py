"""Check whether a process still exists, shared by the parallel and integration tests of killed workers."""

from __future__ import annotations

import os


def is_alive(pid: int) -> bool:
    """Return whether a process with ``pid`` exists (a zombie that is not reaped yet still counts)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
