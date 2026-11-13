"""Check whether a process still exists, shared by the parallel and integration tests of killed workers."""

from __future__ import annotations

import os
import sys

_IS_WINDOWS = sys.platform == 'win32'
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def is_alive(pid: int) -> bool:
    """Return whether a process with ``pid`` is running (on POSIX a zombie that is not reaped yet still counts)."""
    if _IS_WINDOWS:
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _windows_process_is_running(pid: int) -> bool:  # pragma: no cover
    """Open the process and read its exit code: ``os.kill(pid, 0)`` is a console event on Windows, not a probe."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
