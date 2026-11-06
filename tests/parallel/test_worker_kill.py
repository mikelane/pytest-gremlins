"""Finding descendants of a hung worker when ``ps`` is missing (issue #976)."""

from __future__ import annotations

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
