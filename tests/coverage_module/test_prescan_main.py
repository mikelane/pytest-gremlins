"""The coverage pre-scan launcher runs pytest on the node ids it finds in a file (issue #485)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.coverage import prescan_main
from pytest_gremlins.node_id_file import (
    NODE_IDS_FILE_OPTION,
    write_node_ids_file,
)

LOCAL_TESTS = """
import localmod


def test_local():
    assert localmod.VALUE == 1


def test_other():
    assert 0
"""


def _record_pytest_main(monkeypatch: pytest.MonkeyPatch, exit_code: int = 0) -> list[list[str]]:
    received: list[list[str]] = []

    def fake_main(args: list[str]) -> int:
        received.append(list(args))
        return exit_code

    monkeypatch.setattr(prescan_main.pytest, 'main', fake_main)
    return received


@pytest.mark.medium
class DescribePrescanMain:
    def it_hands_pytest_the_original_arguments_followed_by_the_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received = _record_pytest_main(monkeypatch)
        option = f'{NODE_IDS_FILE_OPTION}={write_node_ids_file(["a.py::t1", "b.py::t2"], tmp_path)}'

        prescan_main.main(['-p', 'no:gremlins', '--tb=no', option, '-q'])

        assert received == [['-p', 'no:gremlins', '--tb=no', '-q', 'a.py::t1', 'b.py::t2']]

    def it_returns_the_exit_code_of_pytest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _record_pytest_main(monkeypatch, exit_code=5)

        assert prescan_main.main(['-q']) == 5

    def it_takes_its_arguments_from_the_command_line_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        received = _record_pytest_main(monkeypatch)
        monkeypatch.setattr(sys, 'argv', ['prescan_main', '-q', 'a.py::t'])

        prescan_main.main()

        assert received == [['-q', 'a.py::t']]


@pytest.mark.medium
class DescribePrescanMainUnderCoverage:
    """``coverage run -m prescan_main`` must behave like ``coverage run -m pytest``."""

    def it_keeps_the_working_directory_importable(self, tmp_path: Path) -> None:
        project = tmp_path / 'project'
        project.mkdir()
        (project / 'localmod.py').write_text('VALUE = 1\n', encoding='utf-8')
        (project / 'tests').mkdir()
        (project / 'tests' / 'test_local.py').write_text(LOCAL_TESTS, encoding='utf-8')
        rcfile = tmp_path / 'rc'
        rcfile.write_text('[run]\nsource = .\n', encoding='utf-8')
        option = f'{NODE_IDS_FILE_OPTION}={write_node_ids_file(["tests/test_local.py::test_local"], tmp_path)}'
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}

        completed = subprocess.run(
            [
                sys.executable,
                '-m',
                'coverage',
                'run',
                f'--rcfile={rcfile}',
                '-m',
                'pytest_gremlins.coverage.prescan_main',
                '-p',
                'no:cacheprovider',
                '-o',
                'addopts=',
                '--tb=short',
                '-q',
                option,
            ],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert '1 passed' in completed.stdout
