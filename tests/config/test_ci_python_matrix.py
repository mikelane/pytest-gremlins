"""The main CI test matrix selects and verifies the Python version requested for each leg."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'
MATRIX_PYTHON = '${{ matrix.python-version }}'
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == 'win32', reason='runs the bash guard step with a POSIX fake uv executable'
)


def _test_job() -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))
    return dict(workflow['jobs']['test'])


def _guard_step() -> dict[str, Any]:
    steps: list[dict[str, Any]] = _test_job()['steps']
    return next(step for step in steps if step.get('name') == 'Verify the matrix Python')


def _run_guard(tmp_path: Path, expected: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    fake_uv = bin_dir / 'uv'
    fake_uv.write_text(
        '#!/bin/sh\n'
        'test "$1" = run || { echo "Expected uv run, got $1" >&2; exit 64; }\n'
        'test "$2" = python || { echo "Expected uv run python, got $2" >&2; exit 64; }\n'
        'shift 2\n'
        'exec "$GUARD_TEST_PYTHON" "$@"\n',
        encoding='utf-8',
    )
    fake_uv.chmod(0o755)
    return subprocess.run(
        ['bash', '-eo', 'pipefail', '-c', _guard_step()['run']],  # noqa: S607
        cwd=tmp_path,
        env={
            'PATH': f'{bin_dir}:/usr/bin:/bin',
            'EXPECTED_PYTHON': expected,
            'GUARD_TEST_PYTHON': sys.executable,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeCIPythonMatrix:
    def it_selects_the_matrix_python_for_every_uv_command(self) -> None:
        assert _test_job()['env']['UV_PYTHON'] == MATRIX_PYTHON

    def it_verifies_the_interpreter_before_running_the_tests(self) -> None:
        steps: list[dict[str, Any]] = _test_job()['steps']
        guard = _guard_step()
        guard_index = steps.index(guard)
        test_index = next(index for index, step in enumerate(steps) if 'coverage run -m pytest' in step.get('run', ''))

        assert guard['shell'] == 'bash'
        assert guard['env']['EXPECTED_PYTHON'] == MATRIX_PYTHON
        assert 'uv run python' in guard['run']
        assert guard_index < test_index
        for command in steps[test_index]['run'].splitlines():
            assert command.startswith('uv run ')


@pytest.mark.medium
@POSIX_ONLY
class DescribeCIPythonMatrixGuard:
    def it_accepts_the_matrix_python_version(self, tmp_path: Path) -> None:
        expected = f'{sys.version_info.major}.{sys.version_info.minor}'
        mismatched = '3.11' if expected != '3.11' else '3.12'

        accepted = _run_guard(tmp_path, expected)
        rejected = _run_guard(tmp_path, mismatched)

        assert accepted.returncode == 0, accepted.stderr
        assert f'uv run selected Python {expected}' in accepted.stdout
        assert rejected.returncode != 0
        assert f'Expected Python {mismatched}' in rejected.stderr
        assert f'selected Python {expected}' in rejected.stderr
