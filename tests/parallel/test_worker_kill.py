"""Finding descendants of a hung worker when ``ps`` is missing (issue #976)."""

from __future__ import annotations

from pathlib import Path

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
