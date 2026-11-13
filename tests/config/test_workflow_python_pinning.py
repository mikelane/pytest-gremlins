"""Every workflow job runs the Python it asks for, not the one in ``.python-version``.

``uv sync`` follows ``.python-version`` (3.14.0) unless ``UV_PYTHON`` says otherwise, so a job that only runs
``uv python install 3.11`` still tests 3.14. Each job must set ``UV_PYTHON`` to the version it installs.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
MATRIX_VERSION = '${{ matrix.python-version }}'
INSTALL_PATTERN = re.compile(r'uv python install (\$\{\{ [^}]+\}\}|\S+)')
MATRIX_WORKFLOWS = ['ci.yml', 'release.yml']


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


@pytest.mark.medium
class DescribeWorkflowPythonPinning:
    @pytest.mark.parametrize('workflow_name', MATRIX_WORKFLOWS)
    def it_sets_uv_python_from_the_matrix_version(self, workflow_name: str) -> None:
        job = _jobs(workflow_name)['test']

        assert job['env']['UV_PYTHON'] == MATRIX_VERSION

    @pytest.mark.parametrize('workflow_name', MATRIX_WORKFLOWS)
    def it_fails_the_matrix_job_when_the_interpreter_differs(self, workflow_name: str) -> None:
        steps = _jobs(workflow_name)['test']['steps']
        sync_index = next(i for i, step in enumerate(steps) if step.get('run', '').startswith('uv sync'))
        guards = [step for step in steps[sync_index + 1 :] if 'sys.version_info' in step.get('run', '')]

        assert len(guards) == 1
        assert guards[0]['shell'] == 'bash'
        assert MATRIX_VERSION in guards[0]['run']

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
