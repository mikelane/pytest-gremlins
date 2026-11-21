"""Every workflow job that installs a Python runs that Python, not the one in ``.python-version``.

``uv sync`` follows ``.python-version`` unless ``UV_PYTHON`` says otherwise, so a job that only runs
``uv python install 3.11`` still tests the ``.python-version`` interpreter. Each job that runs
``uv python install <version>`` must set ``UV_PYTHON`` to that version, and the ci.yml test matrix checks the
interpreter before running the suite. Jobs with no install step follow ``.python-version`` and are not checked.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
MATRIX_VERSION = '${{ matrix.python-version }}'
INSTALL_PATTERN = re.compile(r'^\s*uv python install\s+(?:-\S+\s+)*(\$\{\{ [^}]+\}\}|[^-\s]\S*)', re.MULTILINE)
GUARD_STEP_NAME = 'Verify the matrix Python'
TEST_COMMAND = 'coverage run -m pytest'
RUNNING_VERSION = f'{sys.version_info.major}.{sys.version_info.minor}'
MISMATCHED_VERSION = '2.7'
EXPECTED_INSTALLING_JOBS = {'ci.yml:test', 'large-tier.yml:large', 'release.yml:large-tests'}
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == 'win32', reason='runs the bash guard step with a POSIX fake uv executable'
)


def _jobs(workflow_name: str) -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load((WORKFLOWS_DIR / workflow_name).read_text(encoding='utf-8'))
    return dict(workflow['jobs'])


def _installed_versions(job: dict[str, Any]) -> list[str]:
    return [match.group(1) for step in job.get('steps', []) for match in INSTALL_PATTERN.finditer(step.get('run', ''))]


def _installing_jobs() -> list[Any]:
    return [
        pytest.param(job, id=f'{workflow.name}:{job_name}')
        for workflow in sorted(WORKFLOWS_DIR.glob('*.yml'))
        for job_name, job in _jobs(workflow.name).items()
        if _installed_versions(job)
    ]


INSTALLING_JOBS = _installing_jobs()


def _matrix_steps() -> list[dict[str, Any]]:
    return list(_jobs('ci.yml')['test']['steps'])


def _find_step(description: str, matches: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    for step in _matrix_steps():
        if matches(step):
            return step
    return pytest.fail(f'no step {description} in the ci.yml test job')


def _guard_step() -> dict[str, Any]:
    return _find_step(f'named {GUARD_STEP_NAME!r}', lambda step: step.get('name') == GUARD_STEP_NAME)


def _test_step() -> dict[str, Any]:
    return _find_step(f'running {TEST_COMMAND!r}', lambda step: TEST_COMMAND in step.get('run', ''))


def _describe(result: subprocess.CompletedProcess[str]) -> str:
    return f'returncode={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}'


def _run_guard(tmp_path: Path, expected_python: str) -> subprocess.CompletedProcess[str]:
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
            'EXPECTED_PYTHON': expected_python,
            'GUARD_TEST_PYTHON': sys.executable,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeWorkflowPythonPinning:
    def it_selects_the_matrix_python_for_the_test_job(self) -> None:
        job = _jobs('ci.yml')['test']

        assert job['env']['UV_PYTHON'] == MATRIX_VERSION

    def it_finds_the_jobs_that_install_a_python(self) -> None:
        found = {param.id for param in INSTALLING_JOBS}

        assert found >= EXPECTED_INSTALLING_JOBS, f'jobs no longer found: {sorted(EXPECTED_INSTALLING_JOBS - found)}'

    @pytest.mark.parametrize('job', INSTALLING_JOBS)
    def it_pins_uv_python_to_the_version_the_job_installs(self, job: dict[str, Any]) -> None:
        installed = set(_installed_versions(job))

        assert {(job.get('env') or {}).get('UV_PYTHON')} == installed, (
            f'set job-level UV_PYTHON to the installed version {sorted(installed)}'
        )

    @pytest.mark.parametrize(
        ('run', 'version'),
        [
            ('uv python install 3.12', '3.12'),
            ('uv python install --default 3.12', '3.12'),
            ('uv python install -r 3.12', '3.12'),
            ('uv python install ${{ matrix.python-version }}', MATRIX_VERSION),
            ('echo ok\nuv python install 3.13\nuv sync', '3.13'),
        ],
    )
    def it_reads_the_version_a_step_installs(self, run: str, version: str) -> None:
        assert _installed_versions({'steps': [{'run': run}]}) == [version]

    @pytest.mark.parametrize(
        'run',
        ['# uv python install 3.12', 'echo "uv python install 3.12"', 'uv sync --python 3.12'],
    )
    def it_ignores_a_mention_that_does_not_install_a_python(self, run: str) -> None:
        assert _installed_versions({'steps': [{'run': run}]}) == []


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

    def it_never_overrides_the_interpreter_in_the_test_step(self) -> None:
        commands = _test_step()['run'].splitlines()
        uv_options = [token for command in commands for token in shlex.split(command.split(' coverage ')[0])]

        assert [token for token in uv_options if token in {'--python', '-p'} or token.startswith('--python=')] == []

    def it_sets_no_step_level_uv_python_in_the_test_step(self) -> None:
        assert 'UV_PYTHON' not in (_test_step().get('env') or {})

    def it_runs_the_guard_unconditionally_and_fails_the_job_on_a_mismatch(self) -> None:
        guard = _guard_step()

        assert 'if' not in guard
        assert guard.get('continue-on-error', False) is False

    @POSIX_ONLY
    def it_accepts_the_matrix_python_version(self, tmp_path: Path) -> None:
        result = _run_guard(tmp_path, RUNNING_VERSION)

        assert result.returncode == 0, _describe(result)
        assert f'uv run selected Python {RUNNING_VERSION}' in result.stdout, _describe(result)
        assert f'executable: {sys.executable}' in result.stdout, _describe(result)
        assert f'version: {sys.version}' in result.stdout, _describe(result)

    @POSIX_ONLY
    @pytest.mark.parametrize('expected_python', [MISMATCHED_VERSION, RUNNING_VERSION[:-1]])
    def it_rejects_a_python_version_other_than_the_matrix_one(self, tmp_path: Path, expected_python: str) -> None:
        result = _run_guard(tmp_path, expected_python)

        assert result.returncode == 1, _describe(result)
        annotation = (
            f'::error title=Wrong Python::Expected Python {expected_python}, '
            f"uv run selected Python {RUNNING_VERSION}; check the job's UV_PYTHON"
        )
        assert annotation in result.stdout, _describe(result)
        assert f'Expected Python {expected_python}, selected Python {RUNNING_VERSION}' in result.stderr, _describe(
            result
        )
