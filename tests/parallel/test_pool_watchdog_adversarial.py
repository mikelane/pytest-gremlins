"""Adversarial probes of the pool watchdog (issue #976): ways a hung gremlin still outlives its deadline."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    wait,
)
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from pytest_gremlins.parallel.pool import (
    WorkerPool,
    WorkerResult,
    _Job,
)
from pytest_gremlins.parallel.worker_kill import kill_process_trees
from pytest_gremlins.reporting.results import GremlinResultStatus
from tests.parallel.watchdog_workers import run_scripted

HARD_DEADLINE_SECONDS = 50
SLACK_SECONDS = 3
"""Allowance for worker spawns, the 1 s watchdog tick and a loaded machine."""
FOREVER = '3600'


def _submit(pool: WorkerPool, gremlin_id: str, sleep_seconds: str, rootdir: Path) -> Future[WorkerResult]:
    return pool.submit(
        gremlin_id=gremlin_id,
        test_command=[sleep_seconds],
        rootdir=str(rootdir),
        instrumented_dir=None,
        env_vars={},
    )


def _drive(pool: WorkerPool, futures: list[Future[WorkerResult]]) -> dict[int, float]:
    """Drive the watchdog until every future is done; return the monotonic time each future finished at."""
    finished_at: dict[int, float] = {}
    deadline = time.monotonic() + HARD_DEADLINE_SECONDS
    pending = set(futures)
    while pending:
        if time.monotonic() > deadline:
            pytest.fail(f'{len(pending)} future(s) still pending after {HARD_DEADLINE_SECONDS}s: the pool hung')
        pool.service()
        done, pending = wait(pending, timeout=0.1)
        now = time.monotonic()
        finished_at.update({id(future): now for future in done})
    return finished_at


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.large
class DescribeAHungGremlinInFlightWhenAnotherHangIsCaught:
    def it_times_out_within_timeout_plus_grace_of_its_latest_start(self, tmp_path: Path) -> None:
        timeout, grace = 4, 0.5
        pool = WorkerPool(max_workers=2, timeout=timeout, grace_seconds=grace, worker_target=run_scripted)
        with pool:
            first_hung = _submit(pool, 'first-hung', FOREVER, tmp_path)
            quick = _submit(pool, 'quick', '1', tmp_path)
            second_hung = _submit(pool, 'second-hung', FOREVER, tmp_path)
            submitted_at = time.monotonic()
            finished_at = _drive(pool, [first_hung, quick, second_hung])

        # A hung gremlin is scored within timeout + grace of its latest start. second-hung starts about 1 s in,
        # so it has run less than its timeout when first-hung is caught and the pool is rebuilt. It then restarts,
        # and its deadline restarts with it: the bound is one timeout before the rebuild plus timeout + grace after.
        # The reset is bounded per rebuild: every rebuild scores at least one gremlin for good, so the run always
        # progresses, and a gremlin's clock restarts only when another gremlin's hang rebuilds the pool while it is
        # still under its timeout.
        assert finished_at[id(second_hung)] - submitted_at < timeout + timeout + grace + SLACK_SECONDS


def _spawn_command_with_orphaned_grandchild(tmp_path: Path) -> tuple[subprocess.Popen[bytes], Path]:
    """Start a worker whose test command (its own process group, as run_bounded makes it) orphans a grandchild.

    The command starts a helper that forks a grandchild and exits, so the grandchild is adopted by init: no
    parent link leads to it any more, but it stays in the command's process group.
    """
    grandchild_pid_file = tmp_path / 'grandchild.pid'
    command_script = (
        'import os, subprocess, sys, time\n'
        'helper = subprocess.Popen([sys.executable, "-c", '
        '"import os, time\\n'
        'if os.fork() == 0:\\n'
        f'    open({str(grandchild_pid_file)!r}, \\"w\\").write(str(os.getpid()))\\n'
        '    time.sleep(3600)\\n'
        '"])\n'
        'helper.wait()\n'
        'time.sleep(3600)\n'
    )
    worker_script = (
        'import subprocess, sys, time\n'
        f'subprocess.Popen([sys.executable, "-c", {command_script!r}], start_new_session=True)\n'
        'time.sleep(3600)\n'
    )
    worker = subprocess.Popen([sys.executable, '-c', worker_script])
    deadline = time.monotonic() + 10
    while not grandchild_pid_file.exists() or not grandchild_pid_file.read_text():
        if time.monotonic() > deadline:
            worker.kill()
            pytest.fail('the grandchild never started')
        time.sleep(0.05)
    return worker, grandchild_pid_file


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeKillingAWorkerWhoseTestCommandOrphanedAGrandchild:
    def it_kills_the_grandchild_that_stayed_in_the_commands_process_group(self, tmp_path: Path) -> None:
        worker, grandchild_pid_file = _spawn_command_with_orphaned_grandchild(tmp_path)
        grandchild_pid = int(grandchild_pid_file.read_text())
        try:
            kill_process_trees([worker.pid])
            worker.wait(timeout=10)
            time.sleep(0.2)
            alive = _is_alive(grandchild_pid)
        finally:
            subprocess.run(['kill', '-9', str(grandchild_pid)], check=False, capture_output=True)  # noqa: S607

        assert not alive


@pytest.mark.medium
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeKillingAWorkerWhenPsIsUnavailable:
    def it_still_kills_the_test_command_the_worker_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        child_pid_file = tmp_path / 'child.pid'
        script = (
            'import subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])\n'
            f'open({str(child_pid_file)!r}, "w").write(str(child.pid))\n'
            'time.sleep(3600)\n'
        )
        worker = subprocess.Popen([sys.executable, '-c', script])
        deadline = time.monotonic() + 10
        while not child_pid_file.exists() or not child_pid_file.read_text():
            assert time.monotonic() < deadline, 'the child never started'
            time.sleep(0.05)
        child_pid = int(child_pid_file.read_text())
        monkeypatch.setenv('PATH', str(tmp_path / 'no-ps-here'))
        try:
            kill_process_trees([worker.pid])
            worker.wait(timeout=10)
            time.sleep(0.2)
            alive = _is_alive(child_pid)
        finally:
            subprocess.run(['/bin/kill', '-9', str(child_pid)], check=False, capture_output=True)

        assert not alive


def _stubbed_pool(timeout: int = 30) -> WorkerPool:
    """A pool whose executor is never started: submit() records jobs, and nothing runs them."""
    pool = WorkerPool(max_workers=1, timeout=timeout, grace_seconds=1)
    pool._executor = object()  # type: ignore[assignment]
    pool._dispatch = lambda _job: None  # type: ignore[method-assign,assignment]
    pool._reports = multiprocessing.get_context().SimpleQueue()
    return pool


def _submit_stub(pool: WorkerPool, gremlin_id: str) -> Future[WorkerResult]:
    return pool.submit(gremlin_id=gremlin_id, test_command=['x'], rootdir='.', instrumented_dir=None, env_vars={})


def _survived(gremlin_id: str) -> WorkerResult:
    return WorkerResult(gremlin_id=gremlin_id, status=GremlinResultStatus.SURVIVED, execution_time_ms=0.0)


@pytest.mark.small
class DescribeTheWatchdogCostOnALongRun:
    # service() runs once per completed gremlin, so a per-call cost that grows with finished gremlins makes the
    # run quadratic (about 20 s of parent CPU at 10 000 gremlins). The property checked is structural, not timed:
    # once service() has seen a gremlin finish, no later call looks at that gremlin again.
    def it_drops_every_finished_gremlin_from_the_jobs_it_watches(self) -> None:
        pool = _stubbed_pool()
        for n in range(1_000):
            _submit_stub(pool, f'g{n}').set_result(_survived(f'g{n}'))
        _submit_stub(pool, 'still-running')

        pool.service()

        assert list(pool._jobs) == ['still-running']

    def it_checks_only_the_unfinished_gremlin_for_a_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = _stubbed_pool()
        for n in range(1_000):
            _submit_stub(pool, f'g{n}').set_result(_survived(f'g{n}'))
        _submit_stub(pool, 'still-running')
        pool.service()
        checked: list[str] = []

        def record_check(job: _Job, _now: float) -> bool:
            checked.append(job.gremlin_id)
            return False

        monkeypatch.setattr(pool, '_is_overdue', record_check)

        pool.service()

        assert checked == ['still-running']


@pytest.mark.medium
class DescribeAGremlinWhoseRealVerdictLandsWhileTheWatchdogScoresIt:
    def it_does_not_report_it_as_scored_by_the_watchdog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The manager thread can settle a gremlin's future between service() picking it as overdue and settling
        # it TIMEOUT. The TIMEOUT is then ignored (the real verdict stands), but its id is still returned, so the
        # terminal summary says the watchdog scored a gremlin that in fact survived.
        from pytest_gremlins.parallel import pool as pool_module  # noqa: PLC0415

        pool = _stubbed_pool(timeout=1)
        pool._executor = _NoProcessExecutor()  # type: ignore[assignment]
        pool._start_executor = lambda: None  # type: ignore[method-assign]
        future = _submit_stub(pool, 'finishes-at-its-deadline')
        pool._jobs['finishes-at-its-deadline'].started_at = time.monotonic() - 10
        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)

        def verdict_lands_while_scoring(job: _Job, now: float) -> WorkerResult:
            future.set_result(_survived('finishes-at-its-deadline'))
            return WorkerResult(job.gremlin_id, GremlinResultStatus.TIMEOUT, execution_time_ms=now)

        monkeypatch.setattr(pool, '_timeout_result', verdict_lands_while_scoring)

        scored = pool.service()

        assert future.result().status == GremlinResultStatus.SURVIVED
        assert scored == []


class _NoProcessExecutor:
    _processes: dict[int, object] = {}  # noqa: RUF012

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:  # noqa: ARG002
        return


@pytest.mark.medium
class DescribeReadingProcWithAnUndecodableCommandName:
    def it_still_finds_the_descendants(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Any process on the machine can name itself with arbitrary bytes (prctl PR_SET_NAME, or an executable
        # with a Latin-1 file name). When ps is missing, one such /proc/<pid>/stat raised UnicodeDecodeError out
        # of the kill, out of service(), and out of the whole mutation run, leaving the hung worker alive.
        from pytest_gremlins.parallel import worker_kill  # noqa: PLC0415

        monkeypatch.setattr(worker_kill, 'PS_COMMAND', '/nonexistent/ps')
        monkeypatch.setattr(worker_kill, 'FIXED_PATH_PS_COMMAND', '/nonexistent/ps')
        for pid, comm, parent in [(10, b'python', 1), (11, b'pytest', 10), (12, b'caf\xe9', 1)]:
            (tmp_path / str(pid)).mkdir()
            (tmp_path / str(pid) / 'stat').write_bytes(b'%d (%s) S %d %d %d 0\n' % (pid, comm, parent, pid, pid))
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path)

        assert worker_kill.descendants_of(10) == [11]

    def it_falls_back_to_proc_when_ps_prints_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from pytest_gremlins.parallel import worker_kill  # noqa: PLC0415

        def empty_ps(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, returncode=1, stdout='')

        monkeypatch.setattr(subprocess, 'run', empty_ps)
        for pid, parent in [(10, 1), (11, 10)]:
            (tmp_path / str(pid)).mkdir()
            (tmp_path / str(pid) / 'stat').write_text(f'{pid} (x) S {parent} {pid} {pid} 0\n')
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path)

        assert worker_kill.descendants_of(10) == [11]


@pytest.mark.small
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process groups')
class DescribeTheProcessGroupsAKillSignals:
    def it_never_signals_the_runs_group_the_workers_group_or_an_exited_descendants_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pytest_gremlins.parallel import worker_kill  # noqa: PLC0415

        main_group, worker_group, command_group = os.getpgrp(), 7001, 7002
        groups = {100: worker_group, 101: main_group, 102: worker_group, 103: command_group}

        def getpgid(pid: int) -> int:
            if pid not in groups:
                raise ProcessLookupError(pid)
            return groups[pid]

        signalled: list[int] = []
        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', False)
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda _root: [101, 102, 103, 104])
        monkeypatch.setattr(os, 'getpgid', getpgid)
        monkeypatch.setattr(os, 'killpg', lambda group, _signal: signalled.append(group))
        monkeypatch.setattr(os, 'kill', lambda _pid, _signal: None)

        worker_kill.kill_process_trees([100])

        assert signalled == [command_group]


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeARebuildThatRestartsAHealthyGremlin:
    def it_leaves_no_test_command_of_any_attempt_running(self, tmp_path: Path) -> None:
        # healthy starts on the worker 'quick' frees (about 3 s in) and is still inside its 6 s timeout when
        # 'hung' is caught at 6.5 s, so it restarts. Its first test command belonged to a worker the rebuild killed.
        from tests.parallel.watchdog_workers import run_with_test_command  # noqa: PLC0415

        pool = WorkerPool(max_workers=2, timeout=6, grace_seconds=0.5, worker_target=run_with_test_command)
        with pool:
            futures = [
                _submit(pool, 'hung', FOREVER, tmp_path),
                _submit(pool, 'quick', '3', tmp_path),
                _submit(pool, 'healthy', '5', tmp_path),
            ]
            _drive(pool, futures)
            statuses = [future.result().status for future in futures]
        child_pids = [int(path.read_text()) for path in tmp_path.glob('*.child')]
        healthy_attempts = len(list(tmp_path.glob('healthy.*.child')))
        time.sleep(0.5)
        alive = [pid for pid in child_pids if _is_alive(pid)]
        for pid in alive:
            subprocess.run(['/bin/kill', '-9', str(pid)], check=False, capture_output=True)

        assert statuses == [GremlinResultStatus.TIMEOUT, GremlinResultStatus.SURVIVED, GremlinResultStatus.SURVIVED]
        assert healthy_attempts == 2, 'healthy was not restarted: the probe did not exercise a rebuild'
        assert alive == []


_RUN_WITH_UNDECODABLE_PROC = """
import sys, time
from concurrent.futures import wait
from pathlib import Path
from pytest_gremlins.parallel import worker_kill
from pytest_gremlins.parallel.pool import WorkerPool
from tests.parallel.watchdog_workers import run_scripted


def main():
    fake_proc = Path(sys.argv[1])
    (fake_proc / '12').mkdir()
    (fake_proc / '12' / 'stat').write_bytes(b'12 (caf\\xe9) S 1 12 12 0\\n')
    worker_kill.PS_COMMAND = worker_kill.FIXED_PATH_PS_COMMAND = '/nonexistent/ps'
    worker_kill.PROC_ROOT = fake_proc
    with WorkerPool(max_workers=1, timeout=1, grace_seconds=0.2, worker_target=run_scripted) as pool:
        future = pool.submit('hung', ['3600'], sys.argv[2], None, {})
        try:
            while not future.done():
                pool.service()
                wait([future], timeout=0.1)
        except Exception as error:
            print('service raised', type(error).__name__, flush=True)
            raise
    print('pool exited', future.result().status.name, flush=True)


if __name__ == '__main__':
    main()
"""


@pytest.mark.large
@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process tree')
class DescribeAKillThatFailsWhileListingTheProcessTable:
    def it_does_not_leave_the_run_waiting_on_the_hung_worker(self, tmp_path: Path) -> None:
        # With no ps, one undecodable /proc/<pid>/stat makes kill_process_trees raise before it kills anything.
        # The error leaves service(), and the pool's __exit__ then calls shutdown(wait=True) on the executor that
        # still holds the hung worker: the run waits for ever, which is the hang #976 exists to end.
        script = tmp_path / 'run_with_undecodable_proc.py'
        script.write_text(_RUN_WITH_UNDECODABLE_PROC)
        (tmp_path / 'proc').mkdir()
        repo_root = Path(__file__).resolve().parents[2]
        run = subprocess.Popen(
            [sys.executable, str(script), str(tmp_path / 'proc'), str(tmp_path)],
            env={**os.environ, 'PYTHONPATH': str(repo_root)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            output, _ = run.communicate(timeout=30)
            finished = True
        except subprocess.TimeoutExpired:
            os.killpg(run.pid, signal.SIGKILL)
            output, _ = run.communicate()
            finished = False

        assert finished, f'the run never ended after the watchdog fired; output:\n{output}'
        assert 'pool exited TIMEOUT' in output, output
        assert not _is_alive(int((tmp_path / 'hung.pid').read_text()))
