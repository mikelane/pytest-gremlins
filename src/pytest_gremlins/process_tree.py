"""Run a test command so that a timeout ends the whole process tree, not only its first process (#975).

``subprocess.run(timeout=...)`` kills only the direct child. Anything that child started (a multiprocessing
pool, a server fixture, a ``subprocess`` call in a test) keeps running after every timeout, and on Windows it
also keeps the output pipes open, so the final ``communicate()`` of ``subprocess.run`` has no end.
:func:`run_bounded` puts the command in its own process group (a session on POSIX), kills the group on a
timeout or an interrupt, and bounds the wait for the pipes to drain.

Because the command leaves the caller's process group, signals sent to that group no longer reach it. The module
keeps a registry of live commands and ends them (:func:`kill_live_commands`, which SIGKILLs at once) from these
places:

* An ``atexit`` hook, registered when this module is imported, covers interpreter exit and a ``KeyboardInterrupt``
  that unwinds the main thread while a command runs in another thread.
* :func:`sigterm_cleanup` (the main process) and :func:`install_worker_sigterm_cleanup` (the pool worker
  initializer) handle SIGTERM. The main process's handler also SIGTERMs every ``multiprocessing`` child it has, not
  only pool workers, so each worker's handler ends the commands it started.
* An ``os.register_at_fork`` hook, also registered at import, empties the registry in a forked child, which must not
  end its parent's commands.

A SIGKILL of the calling process cannot be handled, so each calling process also starts a watchdog helper (not on
Windows) that holds the read end of a pipe and kills the commands' process groups when the caller dies and the pipe
reaches end-of-file.
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
    from typing import (
        IO,
        TypeAlias,
    )

    _SignalHandler: TypeAlias = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

TERMINATE_GRACE_SECONDS = 0.5
"""How long the group gets to exit after SIGTERM before SIGKILL (POSIX)."""

PIPE_DRAIN_SECONDS = 5.0
"""How long to wait for the output pipes to close after the kill."""

WORKER_STOP_SECONDS = 2.0
"""How long, in total, the SIGTERM cleanup waits for pool workers to end their commands and exit."""

WATCHDOG_STOP_SECONDS = 2.0
"""How long a normal exit waits for the watchdog helper to see the closed pipe and exit."""

_TASKKILL_TIMEOUT_SECONDS = 10
"""How long Windows ``taskkill`` may take to end a tree before the direct child alone is killed."""

# Never log from the SIGTERM path (kill_live_commands and what it calls): the logging module takes locks, and a signal
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
    _tell_watchdog('+', process.pid)


def _unregister(process: subprocess.Popen[bytes]) -> None:
    with _live_commands_lock:
        _live_commands.pop(process.pid, None)
    _tell_watchdog('-', process.pid)


_WATCHDOG_SOURCE = """
import os, signal, sys
for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
    signal.signal(getattr(signal, name), signal.SIG_IGN)
groups = set()
for line in sys.stdin.buffer:
    try:
        action, group = line[:1], int(line[1:])
    except ValueError:
        continue
    if action == b'+':
        groups.add(group)
    elif action == b'-':
        groups.discard(group)
for group in groups:
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        pass
"""
"""The watchdog program: it keeps the process groups it is told about and SIGKILLs them when its stdin closes."""


_DARWIN_F_SETNOSIGPIPE = 73  # <sys/fcntl.h>; the ``fcntl`` module exposes it only in newer Pythons


def _suppress_sigpipe_on_write(pipe: IO[bytes] | None) -> None:  # pragma: posix cover
    """Make a write to a closed ``pipe`` fail with ``BrokenPipeError`` instead of raising SIGPIPE, where supported.

    macOS delivers a pipe-write SIGPIPE to the process rather than reliably to the writing thread, so masking it in
    the writer does not protect a process that left SIGPIPE at the default action. ``F_SETNOSIGPIPE`` does.
    """
    if sys.platform != 'darwin' or pipe is None:
        return
    import fcntl  # noqa: PLC0415 - POSIX only

    with contextlib.suppress(OSError):
        fcntl.fcntl(pipe.fileno(), getattr(fcntl, 'F_SETNOSIGPIPE', _DARWIN_F_SETNOSIGPIPE), 1)


@contextlib.contextmanager
def _sigpipe_blocked() -> Iterator[None]:  # pragma: posix cover
    """Block SIGPIPE in this thread and consume one raised inside, restoring the mask even if interrupted.

    Linux delivers a pipe-write SIGPIPE to the writing thread, so blocking it there turns the signal into ``EPIPE``.
    """
    was_pending = signal.SIGPIPE in signal.sigpending()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGPIPE})
    try:
        try:
            yield
        finally:
            if not was_pending and signal.SIGPIPE in signal.sigpending():
                signal.sigwait({signal.SIGPIPE})  # returns at once: it is pending
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


class _WatchdogProcess(subprocess.Popen[bytes]):  # pragma: posix cover
    """The watchdog's ``Popen``, which only the process that started it may finalize.

    A forked child inherits the object but not the watchdog, which is not its child. ``Popen`` would warn that the
    subprocess is "still running" when the child drops it.
    """

    def __init__(self, command: Sequence[str]) -> None:
        self.owner = os.getpid()
        super().__init__(  # Intentional: starts the watchdog helper
            command,
            bufsize=0,  # unbuffered: a failed write leaves nothing for a later close() to flush into a broken pipe
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _suppress_sigpipe_on_write(self.stdin)

    def __del__(self) -> None:
        if self.owner == os.getpid():
            super().__del__()


class _Watchdog:  # pragma: posix cover
    """A helper process, in its own session, that ends this process's test commands if this process dies.

    The write end of its stdin is the deadman pipe. It reaches end-of-file only when every holder of the write end
    is gone, whatever killed them (SIGKILL included), and then the watchdog kills the commands' process groups.
    """

    def __init__(self) -> None:
        self.owner = os.getpid()
        self.process = _WatchdogProcess([sys.executable, '-I', '-S', '-c', _WATCHDOG_SOURCE])
        assert self.process.stdin is not None  # noqa: S101 - stdin=PIPE

    def tell(self, action: str, group: int) -> None:
        assert self.process.stdin is not None  # noqa: S101 - stdin=PIPE
        # A write to a pipe whose reader died raises SIGPIPE, which kills a process that left it at the default action
        # (some CLIs and plugins do). macOS is covered by F_SETNOSIGPIPE on the pipe; elsewhere block it for the write.
        with _sigpipe_blocked():
            self.process.stdin.write(f'{action}{group}\n'.encode())
            self.process.stdin.flush()

    def has_died(self) -> bool:
        return self.process.poll() is not None

    def discard(self) -> None:
        """Release a watchdog that died: close the pipe to it. ``poll`` has already reaped it."""
        with contextlib.suppress(OSError, ValueError):
            if self.process.stdin is not None:
                self.process.stdin.close()


_watchdog: _Watchdog | None = None


def watchdog_pid() -> int | None:
    """Return the pid of this process's watchdog, or ``None`` before it was started or where there is none."""
    with _live_commands_lock:
        current = _watchdog
    return current.process.pid if current is not None and current.owner == os.getpid() else None


def _tell_watchdog(action: str, group: int) -> None:
    """Tell the watchdog about a command's process group; best effort, since the run itself does not need it.

    A watchdog that died is replaced, and the commands still running are handed to the new one, so they stay
    protected.
    """
    if sys.platform == 'win32':
        return
    died_pid, start_error = _update_watchdog(action, group)  # pragma: posix cover
    # Logged after the lock is released: a thread that waits on a logging lock while holding the registry lock would
    # deadlock a SIGTERM handler that interrupts the logging thread and then waits on the registry lock.
    if died_pid is not None:  # pragma: posix cover
        logger.debug('The watchdog helper (pid %d) had died; starting a new one for the test commands', died_pid)
    if start_error is not None:  # pragma: posix cover
        logger.debug(
            'Could not start the watchdog helper; a SIGKILL of this process would leave its commands running: %s',
            start_error,
        )


def _update_watchdog(action: str, group: int) -> tuple[int | None, OSError | None]:  # pragma: posix cover
    """Replace a dead watchdog, then tell the current one; return the dead one's pid and any error starting one."""
    global _watchdog  # noqa: PLW0603 - one watchdog per process
    died_pid: int | None = None
    with _live_commands_lock:
        if _watchdog is not None and _watchdog.owner == os.getpid() and _watchdog.has_died():
            died_pid = _watchdog.process.pid
            _watchdog.discard()
            _watchdog = None
        is_new = _watchdog is None or _watchdog.owner != os.getpid()
        if is_new:
            if action == '-' and not _own_live_commands():
                return died_pid, None
            try:
                _watchdog = _Watchdog()
            except OSError as error:
                return died_pid, error
        current = _watchdog
        if current is None:
            return died_pid, None
        groups = [process.pid for process in _own_live_commands()] if is_new else [group]
        for known_group in groups:
            with contextlib.suppress(OSError, ValueError):
                current.tell('+' if is_new else action, known_group)
    return died_pid, None


def live_command_count() -> int:
    """Return how many test commands this process has running now."""
    return len(_own_live_commands())


def _own_live_commands() -> list[subprocess.Popen[bytes]]:
    # A forked pool worker inherits its parent's registry; those commands are not its to end.
    with _live_commands_lock:
        return [process for owner, process in _live_commands.values() if owner == os.getpid()]


def kill_live_commands() -> None:
    """End the process tree of every test command this process has running now.

    This is the cleanup for an interrupt or a SIGTERM, which cannot reach a command that runs in its own session.
    It also runs when the interpreter exits. It cannot help when the process is killed with SIGKILL.
    """
    for process in _own_live_commands():
        with contextlib.suppress(OSError):
            _kill_tree(process)


def _stop_watchdog() -> None:
    """Close the deadman pipe and reap the watchdog at a normal exit, so no zombie or ResourceWarning is left."""
    current = _watchdog
    if current is None or current.owner != os.getpid():
        return
    with contextlib.suppress(OSError, ValueError):  # pragma: posix cover
        if current.process.stdin is not None:
            current.process.stdin.close()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):  # pragma: posix cover
        current.process.wait(timeout=WATCHDOG_STOP_SECONDS)


# Registered first so that it runs last: the live commands are ended before the watchdog is released.
atexit.register(_stop_watchdog)
atexit.register(kill_live_commands)


@contextlib.contextmanager
def kill_live_commands_on_error() -> Iterator[None]:
    """End every running test command if the block raises, including on KeyboardInterrupt.

    Wrap a thread pool that runs commands: its ``with`` block waits for the threads before an interrupt
    propagates, and a thread never sees the interrupt itself.
    """
    try:
        yield
    except BaseException:
        kill_live_commands()
        raise


def _install_sigterm_handler(previous: _SignalHandler) -> _SignalHandler:  # pragma: posix cover
    replaced = signal.getsignal(signal.SIGTERM)

    def end_commands_then_terminate(signum: int, frame: FrameType | None) -> None:
        kill_live_commands()
        _stop_child_processes()
        if callable(previous):
            previous(signum, frame)
        else:
            # Never SIG_IGN: both callers leave an ignored SIGTERM alone and install nothing.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, end_commands_then_terminate)
    return replaced


def _stop_child_processes() -> None:  # pragma: posix cover
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


def install_worker_sigterm_cleanup() -> None:
    """Make SIGTERM end this process's test commands, then terminate the process as usual.

    This is the initializer of the worker pools. A worker is killed with its caller's process group (a CI cancel,
    ``timeout``, ``killpg``), and its commands run in their own sessions, so they would otherwise run on.
    """
    if sys.platform != 'win32' and signal.getsignal(signal.SIGTERM) != signal.SIG_IGN:
        _install_sigterm_handler(signal.SIG_DFL)  # pragma: posix cover


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
    replaced = _install_sigterm_handler(previous)  # pragma: posix cover
    try:  # pragma: posix cover
        yield
    finally:  # pragma: posix cover
        signal.signal(signal.SIGTERM, replaced if replaced is not None else signal.SIG_DFL)


def _forget_inherited_commands() -> None:  # pragma: posix cover
    global _live_commands_lock, _watchdog  # noqa: PLW0603 - a lock held by another thread at fork time stays locked
    _live_commands_lock = threading.RLock()
    _live_commands.clear()
    # The child holds a copy of its parent's watchdog pipe. Closing it here keeps the child from holding the pipe open
    # past the parent's death, which would stop the watchdog from ever seeing end-of-file.
    # Close it through the file object that owns the descriptor: closing the bare number would leave that object to
    # close it a second time when it is dropped, possibly after the number was reused.
    if _watchdog is not None and _watchdog.owner == os.getppid() and _watchdog.process.stdin is not None:
        with contextlib.suppress(OSError, ValueError):
            _watchdog.process.stdin.close()
    _watchdog = None


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_forget_inherited_commands)  # pragma: posix cover


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
    return subprocess.Popen(  # Intentional: runs pytest test commands  # pragma: posix cover
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
            _signal_group(process, signal.SIGTERM)  # pragma: posix cover
            with contextlib.suppress(subprocess.TimeoutExpired):  # pragma: posix cover
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
    finally:
        _kill_tree(process)


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == 'win32':
        _taskkill_tree(process)
    else:  # pragma: posix cover
        _signal_group(process, signal.SIGKILL)


def _signal_group(process: subprocess.Popen[bytes], signal_number: int) -> None:  # pragma: posix cover
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
    except BaseException:
        # An interrupt must not leave the killed command as a zombie that nothing will ever reap.
        _abandon_pipes(process)
        raise
    return stdout, stderr


def _abandon_pipes(process: subprocess.Popen[bytes]) -> None:
    logger.debug(
        'Output pipes of test command (pid %d) still open %ss after the kill; a process outside its group holds them',
        process.pid,
        PIPE_DRAIN_SECONDS,
    )
    if sys.platform != 'win32':
        for pipe in (process.stdout, process.stderr):  # pragma: posix cover
            if pipe is not None:
                pipe.close()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=PIPE_DRAIN_SECONDS)
