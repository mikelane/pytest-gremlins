"""Run a test command so that a timeout ends the whole process tree, not only its first process (#975).

``subprocess.run(timeout=...)`` kills only the direct child. Anything that child started (a multiprocessing
pool, a server fixture, a ``subprocess`` call in a test) keeps running after every timeout, and on Windows it
also keeps the output pipes open, so the final ``communicate()`` of ``subprocess.run`` has no end.
:func:`run_bounded` puts the command in its own process group (a session on POSIX), kills the group on a
timeout or an interrupt, and bounds the wait for the pipes to drain.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Iterator,
        Mapping,
        Sequence,
    )
    from types import FrameType
    from typing import TypeAlias

    _SignalHandler: TypeAlias = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

TERMINATE_GRACE_SECONDS = 0.5
"""How long the group gets to exit after SIGTERM before SIGKILL (POSIX)."""

PIPE_DRAIN_SECONDS = 5.0
"""How long to wait for the output pipes to close after the kill."""

WORKER_STOP_SECONDS = 2.0
"""How long, in total, the SIGTERM cleanup waits for pool workers to end their commands and exit."""

_TASKKILL_TIMEOUT_SECONDS = 10

# Never log from the SIGTERM path (terminate_all and what it calls): the logging module takes locks, and a signal
# handler can interrupt the thread that holds them.
logger = logging.getLogger(__name__)

_live_commands: dict[int, tuple[int, subprocess.Popen[bytes]]] = {}
"""Commands that are running now, by pid, with the pid of the process that started each."""

# Reentrant: a signal handler runs on the main thread, possibly while that thread holds the lock.
_live_commands_lock = threading.RLock()


def run_bounded(
    command: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``command`` with captured output, ending its whole process tree if it outlasts ``timeout``.

    Args:
        command: The command line to run.
        cwd: Working directory of the command.
        env: Environment of the command.
        timeout: Seconds the command may run.

    Returns:
        The completed process, with its captured stdout and stderr.

    Raises:
        subprocess.TimeoutExpired: If the command outlasted ``timeout``. Its process tree has been killed, and
            the output read before the kill is attached.
    """
    process = _start(command, cwd=cwd, env=env)
    _register(process)
    try:
        return _wait_for(process, command, timeout)
    finally:
        _unregister(process)


def _wait_for(
    process: subprocess.Popen[bytes], command: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[bytes]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        try:
            _terminate_tree(process)
        finally:
            # An interrupt during the grace period still reaps the command and closes its pipes.
            stdout, stderr = _drain(process)
        # The exit status tells whether SIGTERM was enough (-15) or the group needed SIGKILL (-9).
        logger.debug(
            'Test command (pid %d) outlasted %ss; its process group was ended, exit status %s',
            process.pid,
            timeout,
            process.returncode,
        )
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from expired
    except BaseException:
        _kill_tree(process)
        _drain(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _register(process: subprocess.Popen[bytes]) -> None:
    with _live_commands_lock:
        _live_commands[process.pid] = (os.getpid(), process)


def _unregister(process: subprocess.Popen[bytes]) -> None:
    with _live_commands_lock:
        _live_commands.pop(process.pid, None)


def live_command_count() -> int:
    """Return how many test commands this process has running now."""
    return len(_own_live_commands())


def _own_live_commands() -> list[subprocess.Popen[bytes]]:
    # A forked pool worker inherits its parent's registry; those commands are not its to end.
    with _live_commands_lock:
        return [process for owner, process in _live_commands.values() if owner == os.getpid()]


def terminate_all() -> None:
    """End the process tree of every test command this process has running now.

    This is the cleanup for an interrupt or a SIGTERM, which cannot reach a command that runs in its own session.
    It also runs when the interpreter exits. It cannot help when the process is killed with SIGKILL.
    """
    for process in _own_live_commands():
        with contextlib.suppress(OSError):
            _kill_tree(process)


atexit.register(terminate_all)


@contextlib.contextmanager
def terminate_all_on_error() -> Iterator[None]:
    """End every running test command if the block raises, including on KeyboardInterrupt.

    Wrap a thread pool that runs commands: its ``with`` block waits for the threads before an interrupt
    propagates, and a thread never sees the interrupt itself.
    """
    try:
        yield
    except BaseException:
        terminate_all()
        raise


def _install_sigterm_handler(previous: _SignalHandler) -> _SignalHandler:
    replaced = signal.getsignal(signal.SIGTERM)

    def end_commands_then_terminate(signum: int, frame: FrameType | None) -> None:
        terminate_all()
        _stop_child_processes()
        if callable(previous):
            previous(signum, frame)
        elif previous != signal.SIG_IGN:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, end_commands_then_terminate)
    return replaced


def _stop_child_processes() -> None:
    """SIGTERM the multiprocessing children (the pool workers) so their own cleanup ends their commands."""
    try:
        children = multiprocessing.active_children()
    except RuntimeError:  # a child was being started or reaped while this handler interrupted the main thread
        return
    for child in children:
        with contextlib.suppress(OSError, ValueError):
            child.terminate()
    deadline = time.monotonic() + WORKER_STOP_SECONDS
    for child in children:
        with contextlib.suppress(OSError, ValueError, AssertionError):
            child.join(max(0.0, deadline - time.monotonic()))


def install_sigterm_cleanup() -> None:
    """Make SIGTERM end this process's test commands, then terminate the process as usual.

    This is the initializer of the worker pools. A worker is killed with its caller's process group (a CI cancel,
    ``timeout``, ``killpg``), and its commands run in their own sessions, so they would otherwise run on.
    """
    if sys.platform != 'win32' and signal.getsignal(signal.SIGTERM) != signal.SIG_IGN:
        _install_sigterm_handler(signal.SIG_DFL)


@contextlib.contextmanager
def sigterm_cleanup() -> Iterator[None]:
    """End this process's test commands on SIGTERM, then hand the signal to the handler that was installed before.

    A previous handler is called; with none (or the default) the default action runs, so the exit status stays
    that of SIGTERM. Pool workers get a SIGTERM too, so they end their own commands. The previous handler is restored
    afterwards. Handlers can only be set from the main thread, so this does nothing anywhere else, and on Windows.
    Nothing is installed where SIGTERM is ignored: the caller asked for it to have no effect. SIGINT is left to pytest.
    """
    previous = signal.getsignal(signal.SIGTERM)
    if (
        sys.platform == 'win32'
        or threading.current_thread() is not threading.main_thread()
        or previous == signal.SIG_IGN
    ):
        yield
        return
    replaced = _install_sigterm_handler(previous)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, replaced if replaced is not None else signal.SIG_DFL)


def _forget_inherited_commands() -> None:
    global _live_commands_lock  # noqa: PLW0603 - a lock held by another thread at fork time stays locked
    _live_commands_lock = threading.RLock()
    _live_commands.clear()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_forget_inherited_commands)


def _start(command: Sequence[str], *, cwd: str, env: Mapping[str, str]) -> subprocess.Popen[bytes]:
    if sys.platform == 'win32':
        return subprocess.Popen(  # Intentional: runs pytest test commands
            command,
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(  # Intentional: runs pytest test commands
        command,
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Ask the tree to exit, then force it; Windows has no polite signal for a group.

    The grace period ends as soon as the command exits, and the SIGKILL is sent even if the wait is interrupted.
    Reaping the command first is safe: its group id stays reserved while any member of the group is alive.
    """
    try:
        if sys.platform != 'win32':
            _signal_group(process, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
    finally:
        _kill_tree(process)


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == 'win32':
        _taskkill_tree(process)
    else:
        _signal_group(process, signal.SIGKILL)


def _signal_group(process: subprocess.Popen[bytes], signal_number: int) -> None:
    # The command is its own group leader (start_new_session), so its pid is the group id.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal_number)


def _taskkill_path() -> str:
    system_root = os.environ.get('SystemRoot', r'C:\Windows')  # noqa: SIM112 - the name Windows defines
    return str(Path(system_root) / 'System32' / 'taskkill.exe')


def _taskkill_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        subprocess.run(  # Intentional: ends the process tree of a timed-out test run
            [_taskkill_path(), '/F', '/T', '/PID', str(process.pid)],
            capture_output=True,
            timeout=_TASKKILL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        process.kill()


def _drain(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Collect what the killed command wrote, giving up if something outside the tree still holds the pipes."""
    try:
        stdout, stderr = process.communicate(timeout=PIPE_DRAIN_SECONDS)
    except subprocess.TimeoutExpired as still_open:
        _abandon_pipes(process)
        return still_open.stdout or b'', still_open.stderr or b''
    return stdout, stderr


def _abandon_pipes(process: subprocess.Popen[bytes]) -> None:
    logger.debug(
        'Output pipes of test command (pid %d) still open %ss after the kill; a process outside its group holds them',
        process.pid,
        PIPE_DRAIN_SECONDS,
    )
    if sys.platform != 'win32':
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=PIPE_DRAIN_SECONDS)
