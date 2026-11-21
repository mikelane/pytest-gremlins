"""Every workflow job runs the Python it asks for, not the one in ``.python-version``.

``uv sync`` follows ``.python-version`` (3.14.0) unless ``UV_PYTHON`` says otherwise, so a job that only runs
``uv python install 3.11`` still tests 3.14. Each job must set ``UV_PYTHON`` to the version it installs, and the
ci.yml test matrix checks the interpreter before running the suite.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
MATRIX_VERSION = '${{ matrix.python-version }}'
INSTALL_PATTERN = re.compile(r'uv python install (\$\{\{ [^}]+\}\}|\S+)')
GUARD_STEP_NAME = 'Verify the matrix Python'
RUNNING_VERSION = f'{sys.version_info.major}.{sys.version_info.minor}'
NEVER_RUNNING_VERSION = '2.7'
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == 'win32', reason='runs the bash guard step with a POSIX fake uv executable'
)


def _jobs(workflow_name: str) -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load((WORKFLOWS_DIR / workflow_name).read_text(encoding='utf-8'))
    return dict(workflow['jobs'])


def _requested_versions(job: dict[str, Any]) -> list[str]:
    versions: list[str] = []
    for step in job.get('steps', []):
        match = INSTALL_PATTERN.search(step.get('run', ''))
        if match:
            versions.append(match.group(1))
    return versions


def _installing_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (workflow.name, job_name, job)
        for workflow in sorted(WORKFLOWS_DIR.glob('*.yml'))
        for job_name, job in _jobs(workflow.name).items()
        if _requested_versions(job)
    ]


INSTALLING_JOBS = _installing_jobs()


def _matrix_steps() -> list[dict[str, Any]]:
    return list(_jobs('ci.yml')['test']['steps'])


def _guard_step() -> dict[str, Any]:
    return next(step for step in _matrix_steps() if step.get('name') == GUARD_STEP_NAME)


def _test_step() -> dict[str, Any]:
    return next(step for step in _matrix_steps() if 'coverage run -m pytest' in step.get('run', ''))


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
class DescribeWorkflowPythonPinning:
    def it_selects_the_matrix_python_for_every_uv_command_in_the_test_matrix(self) -> None:
        job = _jobs('ci.yml')['test']

        assert job['env']['UV_PYTHON'] == MATRIX_VERSION

    @pytest.mark.parametrize(
        ('workflow_name', 'job_name', 'job'),
        INSTALLING_JOBS,
        ids=[f'{workflow}:{name}' for workflow, name, _ in INSTALLING_JOBS],
    )
    def it_pins_uv_python_to_the_version_the_job_installs(
        self, workflow_name: str, job_name: str, job: dict[str, Any]
    ) -> None:
        del workflow_name, job_name
        requested = set(_requested_versions(job))

        assert {job.get('env', {}).get('UV_PYTHON')} == requested


@pytest.mark.medium
class DescribeMatrixInterpreterGuard:
    def it_passes_the_matrix_version_to_a_bash_guard(self) -> None:
        guard = _guard_step()

        assert guard['shell'] == 'bash'
        assert guard['env']['EXPECTED_PYTHON'] == MATRIX_VERSION
        assert 'uv run python' in guard['run']

    def it_runs_the_guard_before_the_tests(self) -> None:
        steps = _matrix_steps()

        assert steps.index(_guard_step()) < steps.index(_test_step())

    def it_runs_every_test_command_through_uv_run(self) -> None:
        commands = _test_step()['run'].splitlines()

        assert [command for command in commands if not command.startswith('uv run ')] == []

    @POSIX_ONLY
    def it_accepts_the_matrix_python_version(self, tmp_path: Path) -> None:
        result = _run_guard(tmp_path, RUNNING_VERSION)

        assert result.returncode == 0, result.stderr
        assert f'uv run selected Python {RUNNING_VERSION}' in result.stdout

    @POSIX_ONLY
    def it_rejects_a_python_version_other_than_the_matrix_one(self, tmp_path: Path) -> None:
        result = _run_guard(tmp_path, NEVER_RUNNING_VERSION)

        assert result.returncode != 0
        assert f'Expected Python {NEVER_RUNNING_VERSION}, selected Python {RUNNING_VERSION}' in result.stderr
