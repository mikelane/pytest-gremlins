"""Finding descendants of a hung worker when ``ps`` is missing (issue #976)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess

import pytest

from pytest_gremlins.parallel import worker_kill


def _fake_proc(root: Path, processes: dict[int, tuple[str, int]]) -> None:
    for pid, (command, parent) in processes.items():
        (root / str(pid)).mkdir()
        (root / str(pid) / 'stat').write_text(f'{pid} ({command}) S {parent} {pid} {pid} 0 -1 4194560\n')
    (root / 'self').mkdir()


@pytest.fixture
def no_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_kill, 'PS_COMMAND', '/nonexistent/ps')
    monkeypatch.setattr(worker_kill, 'FIXED_PATH_PS_COMMAND', '/nonexistent/ps')


@pytest.mark.medium
class DescribeDescendantsFromProc:
    @pytest.mark.usefixtures('no_ps')
    def it_walks_the_parent_links_in_proc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_proc(tmp_path, {10: ('python', 1), 11: ('pytest', 10), 12: ('sleep', 11), 99: ('other', 1)})
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path)

        assert sorted(worker_kill.descendants_of(10)) == [11, 12]

    @pytest.mark.usefixtures('no_ps')
    def it_reads_a_command_name_with_spaces_and_parentheses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_proc(tmp_path, {10: ('python', 1), 11: ('my (odd) cmd', 10)})
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path)

        assert worker_kill.descendants_of(10) == [11]

    @pytest.mark.usefixtures('no_ps')
    def it_skips_entries_whose_stat_is_missing_or_malformed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_proc(tmp_path, {10: ('python', 1), 11: ('pytest', 10)})
        (tmp_path / '12').mkdir()  # the process exited between the listing and the read
        (tmp_path / '13').mkdir()
        (tmp_path / '13' / 'stat').write_text('13 (truncated)\n')
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path)

        assert worker_kill.descendants_of(10) == [11]

    @pytest.mark.usefixtures('no_ps')
    def it_returns_nothing_and_warns_when_neither_ps_nor_proc_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(worker_kill, 'PROC_ROOT', tmp_path / 'missing')

        assert worker_kill.descendants_of(10) == []
        assert 'Cannot list the descendants of worker 10' in caplog.text


@pytest.mark.medium
class DescribeDescendantsFromPs:
    def it_uses_the_listing_when_ps_exits_nonzero_because_a_process_ended_meanwhile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def busy_machine_ps(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, returncode=1, stdout='  10     1\n  11    10\n  12    11\n')

        monkeypatch.setattr(subprocess, 'run', busy_machine_ps)

        assert sorted(worker_kill.descendants_of(10)) == [11, 12]

    def it_falls_back_to_the_fixed_path_ps_when_ps_is_not_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def ps_only_at_fixed_path(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            called.append(command[0])
            if command[0] != worker_kill.FIXED_PATH_PS_COMMAND:
                raise FileNotFoundError(command[0])
            return subprocess.CompletedProcess(command, returncode=0, stdout='  10     1\n  11    10\n')

        monkeypatch.setattr(subprocess, 'run', ps_only_at_fixed_path)

        assert worker_kill.descendants_of(10) == [11]
        assert called == [worker_kill.PS_COMMAND, worker_kill.FIXED_PATH_PS_COMMAND]

    def it_skips_lines_that_are_not_two_pids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def ps_with_noise(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            listing = '  PID  PPID\n  11    10\n  12\n  13 10 extra\n  x1    10\n  14    11\n'
            return subprocess.CompletedProcess(command, returncode=0, stdout=listing)

        monkeypatch.setattr(subprocess, 'run', ps_with_noise)

        assert sorted(worker_kill.descendants_of(10)) == [11, 14]


@pytest.mark.medium  # monkeypatching subprocess.run in a small test would restore the category plugin's blocker
class DescribeKillingOnWindows:
    def it_runs_taskkill_on_each_tree_and_lists_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []

        def record_taskkill(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            commands.append(command)
            return subprocess.CompletedProcess(command, returncode=0)

        def refuse_listing(_root: int) -> list[int]:
            pytest.fail('a Windows kill listed descendants')

        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', True)
        monkeypatch.setattr(worker_kill, 'descendants_of', refuse_listing)
        monkeypatch.setattr(subprocess, 'run', record_taskkill)

        worker_kill.kill_process_trees([100, 200])

        assert commands == [['taskkill', '/PID', '100', '/T', '/F'], ['taskkill', '/PID', '200', '/T', '/F']]

    def it_warns_instead_of_raising_when_taskkill_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def missing_taskkill(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise FileNotFoundError(command[0])

        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', True)
        monkeypatch.setattr(subprocess, 'run', missing_taskkill)

        worker_kill.kill_process_trees([100])

        assert [record.levelno for record in caplog.records] == [logging.WARNING]
        assert 'taskkill' in caplog.records[0].getMessage()
        assert '100' in caplog.records[0].getMessage()


@pytest.mark.small
class DescribeKillingAProcessThisRunMayNotSignal:
    def it_warns_and_still_kills_the_rest_of_the_tree(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        killed: list[int] = []

        def kill_refusing_101(pid: int, _signal: int) -> None:
            if pid == 101:
                raise PermissionError(pid)
            killed.append(pid)

        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', False)
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda _root: [101, 102])
        monkeypatch.setattr(worker_kill, '_groups_to_signal', lambda _root, _descendants: set())
        monkeypatch.setattr(os, 'kill', kill_refusing_101)

        worker_kill.kill_process_trees([100])

        assert killed == [102, 100]
        assert [record.levelno for record in caplog.records] == [logging.WARNING]
        assert '101' in caplog.records[0].getMessage()

    def it_stays_quiet_about_a_process_that_already_exited(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        killed: list[int] = []

        def kill_with_101_gone(pid: int, _signal: int) -> None:
            if pid == 101:
                raise ProcessLookupError(pid)
            killed.append(pid)

        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', False)
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda _root: [101, 102])
        monkeypatch.setattr(worker_kill, '_groups_to_signal', lambda _root, _descendants: set())
        monkeypatch.setattr(os, 'kill', kill_with_101_gone)

        worker_kill.kill_process_trees([100])

        assert killed == [102, 100]
        assert caplog.records == []


@pytest.mark.small
class DescribeKillingSeveralWorkers:
    def it_lists_every_workers_descendants_before_it_kills_anything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Killing one worker breaks the executor, whose manager then terminates the others; a worker that dies
        # that way can no longer be walked, and its test command would be left running.
        events: list[str] = []

        def list_descendants(root: int) -> list[int]:
            events.append(f'list {root}')
            return [root + 1]

        def record_kill(pid: int, _signal: int) -> None:
            events.append(f'kill {pid}')

        monkeypatch.setattr(worker_kill, '_IS_WINDOWS', False)
        monkeypatch.setattr(worker_kill, 'descendants_of', list_descendants)
        monkeypatch.setattr(worker_kill, '_groups_to_signal', lambda _root, _descendants: set())
        monkeypatch.setattr(os, 'kill', record_kill)

        worker_kill.kill_process_trees([100, 200])

        assert events[:2] == ['list 100', 'list 200']
        assert sorted(events[2:]) == ['kill 100', 'kill 101', 'kill 200', 'kill 201']


@pytest.mark.small
class DescribeKillingPidsDirectly:
    def it_warns_about_a_pid_it_may_not_signal_and_still_kills_the_rest(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        killed: list[int] = []

        def kill_refusing_101(pid: int, _signal: int) -> None:
            if pid == 101:
                raise PermissionError(pid)
            killed.append(pid)

        monkeypatch.setattr(os, 'kill', kill_refusing_101)

        worker_kill.sigkill_pids([100, 101, 102])

        assert killed == [100, 102]
        assert [record.levelno for record in caplog.records] == [logging.WARNING]
        assert '101' in caplog.records[0].getMessage()


@pytest.mark.small
class DescribeKillingTheChildrenOfWorkers:
    def it_kills_what_it_finds_under_each_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        killed: list[int] = []
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda root: [root + 1, root + 2])
        monkeypatch.setattr(os, 'kill', lambda pid, _signal: killed.append(pid))

        worker_kill.kill_children_of([100, 200])

        assert sorted(killed) == [101, 102, 201, 202]

    def it_warns_and_goes_on_when_it_cannot_list_one_workers_descendants(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        killed: list[int] = []

        def list_failing_for_100(root: int) -> list[int]:
            if root == 100:
                raise RuntimeError('unreadable')
            return [root + 1]

        monkeypatch.setattr(worker_kill, 'descendants_of', list_failing_for_100)
        monkeypatch.setattr(os, 'kill', lambda pid, _signal: killed.append(pid))

        worker_kill.kill_children_of([100, 200])

        assert killed == [201]
        assert 'Cannot list the descendants of worker 100' in caplog.text
