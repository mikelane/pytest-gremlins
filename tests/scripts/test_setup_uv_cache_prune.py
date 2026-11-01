"""Every setup-uv step that can save a cache prunes it first.

A step saves a cache when ``enable-cache`` is ``true`` or left at its default ``auto``, which counts as on for
``workflow_dispatch`` runs (cut-release.yml, release.yml and docs.yml are dispatched by hand). Only
``enable-cache: false`` opts out.

setup-uv v9.0.0 changed the ``prune-cache`` default from ``true`` to ``false`` (astral-sh/setup-uv#967). Without
pruning, each saved cache holds every downloaded wheel: PR #859's caches measured 109-129 MB per key, against
0-2 MB for the pruned v7.6.0 caches. The repo-wide Actions cache limit is 10 GB, so unpruned caches from a handful
of concurrent PRs evict each other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / '.github' / 'workflows'


def _caching_setup_uv_steps() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for workflow_path in sorted(WORKFLOWS_DIR.glob('*.yml')):
        workflow = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
        for job_id, job in workflow.get('jobs', {}).items():
            for index, step in enumerate(job.get('steps', [])):
                uses = step.get('uses', '')
                inputs = step.get('with') or {}
                if uses.startswith('astral-sh/setup-uv@') and inputs.get('enable-cache') is not False:
                    found.append((f'{workflow_path.name}:{job_id}:{index}', inputs))
    return found


CACHED_STEPS = _caching_setup_uv_steps()


@pytest.mark.small
class DescribeSetupUvCachePruning:
    def it_finds_caching_setup_uv_steps(self) -> None:
        assert len(CACHED_STEPS) > 0

    @pytest.mark.parametrize(('step_id', 'inputs'), CACHED_STEPS, ids=[step_id for step_id, _ in CACHED_STEPS])
    def it_prunes_the_uv_cache_before_saving_it(self, step_id: str, inputs: dict[str, Any]) -> None:
        assert inputs.get('prune-cache') is True, f'{step_id} saves an unpruned uv cache'
