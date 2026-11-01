"""The uv version range in pyproject.toml and in every setup-uv step is one and the same (issue #858).

``uv lock`` from uv older than 0.13.0 rewrites the ``uv.lock`` header ``revision = 5`` to ``revision = 3``. Pinning
a minimum makes an older local uv fail fast, and pinning the same range in CI keeps CI and local uv from drifting.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / '.github' / 'workflows'


def _required_version() -> str:
    pyproject = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    return pyproject['tool']['uv']['required-version']


def _setup_uv_steps() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for workflow_path in sorted(WORKFLOWS_DIR.glob('*.yml')):
        workflow = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
        for job_id, job in workflow.get('jobs', {}).items():
            for index, step in enumerate(job.get('steps', [])):
                if step.get('uses', '').startswith('astral-sh/setup-uv@'):
                    found.append((f'{workflow_path.name}:{job_id}:{index}', step.get('with') or {}))
    return found


SETUP_UV_STEPS = _setup_uv_steps()


@pytest.mark.medium
class DescribeUvVersionPin:
    def it_requires_a_uv_that_keeps_the_lockfile_revision(self) -> None:
        assert _required_version() == '>=0.13.0'

    def it_finds_setup_uv_steps(self) -> None:
        assert len(SETUP_UV_STEPS) > 0

    @pytest.mark.parametrize(('step_id', 'inputs'), SETUP_UV_STEPS, ids=[step_id for step_id, _ in SETUP_UV_STEPS])
    def it_installs_the_uv_range_pyproject_requires(self, step_id: str, inputs: dict[str, Any]) -> None:
        assert inputs.get('version') == _required_version(), f'{step_id} does not pin the required uv version'
