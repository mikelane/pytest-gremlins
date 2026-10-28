"""Black-box regression tests for #533: a ``--gremlins`` run keeps no inline coverage of its own.

Each test runs a real ``pytest --gremlins`` in a throwaway project, with no ``--cov``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_CALC = 'def add(a, b):\n    return a + b\n\n\ndef gt(a, b):\n    return a > b\n'
_TESTS = (
    'import sys\nsys.path.insert(0, "src")\nfrom calc import add, gt\n\n\n'
    'def test_add():\n    assert add(2, 3) == 5\n\n\n'
    'def test_gt():\n    assert gt(3, 2) is True\n    assert gt(2, 3) is False\n'
)
_PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n{filterwarnings}\n[tool.gremlins]\npaths = ["src"]\n'
_HIDE_CTRACER = "import sys\nsys.modules['coverage.tracer'] = None\n"


def _make_project(root: Path, *, warnings_are_errors: bool = False) -> None:
    (root / 'src').mkdir()
    (root / 'src' / 'calc.py').write_text(_CALC)
    (root / 'tests').mkdir()
    (root / 'tests' / 'test_calc.py').write_text(_TESTS)
    filterwarnings = 'filterwarnings = ["error"]\n' if warnings_are_errors else ''
    (root / 'pyproject.toml').write_text(_PYPROJECT.format(filterwarnings=filterwarnings))


def _child_env(root: Path, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    # Windows needs SYSTEMROOT to initialise Winsock; without it any socket() call fails with WinError 10106.
    inherited = {name: os.environ[name] for name in ('SYSTEMROOT',) if name in os.environ}
    return {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(root), **inherited, **(extra_env or {})}


def _run_gremlins(root: Path, *args: str, extra_env: dict[str, str] | None = None) -> str:
    env = _child_env(root, extra_env)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '--gremlins', '-p', 'no:cacheprovider', '-p', 'no:test_categories', *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return result.stdout + result.stderr


def _stray_coverage_files(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob('.coverage*') if p.is_file())


@pytest.mark.medium
class DescribeRunWithoutCoverageTracer:
    """A missing CTracer plus ``filterwarnings = error`` must not crash the controller."""

    @pytest.mark.parametrize('worker_args', [[], ['-n', '2']], ids=['sequential', 'xdist'])
    def it_completes_without_internalerror(self, tmp_path: Path, worker_args: list[str]) -> None:
        _make_project(tmp_path, warnings_are_errors=True)
        hide_dir = tmp_path / 'hide_ctracer'
        hide_dir.mkdir()
        (hide_dir / 'sitecustomize.py').write_text(_HIDE_CTRACER)

        output = _run_gremlins(tmp_path, *worker_args, extra_env={'PYTHONPATH': str(hide_dir)})

        assert 'INTERNALERROR' not in output, output[-3000:]


@pytest.mark.medium
class DescribeRunLeavesNoCoverageDataFiles:
    """No ``.coverage.<host>.pid*`` files are written, whether or not COVERAGE_FILE is set."""

    @pytest.mark.parametrize('worker_args', [[], ['-n', '2']], ids=['sequential', 'xdist'])
    def it_leaves_no_stray_files_in_the_rootdir(self, tmp_path: Path, worker_args: list[str]) -> None:
        _make_project(tmp_path)

        output = _run_gremlins(tmp_path, *worker_args)

        assert 'INTERNALERROR' not in output, output[-3000:]
        assert _stray_coverage_files(tmp_path) == [], output[-3000:]

    def it_leaves_no_suffixed_files_next_to_a_user_coverage_file(self, tmp_path: Path) -> None:
        project = tmp_path / 'project'
        project.mkdir()
        _make_project(project)
        data_dir = tmp_path / 'covdata'
        data_dir.mkdir()

        _run_gremlins(project, extra_env={'COVERAGE_FILE': str(data_dir / 'user.coverage')})

        assert sorted(p.name for p in data_dir.iterdir()) == []
        assert _stray_coverage_files(project) == []


@pytest.mark.small
class DescribeChildEnv:
    def it_forwards_systemroot_so_winsock_can_initialise(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('SYSTEMROOT', 'C:\\Windows')

        assert _child_env(tmp_path)['SYSTEMROOT'] == 'C:\\Windows'

    def it_omits_systemroot_when_the_parent_has_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('SYSTEMROOT', raising=False)

        assert 'SYSTEMROOT' not in _child_env(tmp_path)
