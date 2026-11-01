"""Structural tests for the large-tier jobs in large-tier.yml and release.yml (issue #799)."""

from __future__ import annotations

from pathlib import Path
from typing import (
    Any,
    cast,
)

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / '.github' / 'workflows'


def _jobs(workflow_name: str) -> dict[str, Any]:
    return cast('dict[str, Any]', yaml.safe_load((WORKFLOWS_DIR / workflow_name).read_text(encoding='utf-8'))['jobs'])


@pytest.mark.medium
class DescribeLargeTierJobTimeouts:
    def it_gives_the_release_large_job_the_same_timeout_as_the_nightly_job(self) -> None:
        nightly_timeout = _jobs('large-tier.yml')['large']['timeout-minutes']

        assert _jobs('release.yml')['large-tests']['timeout-minutes'] == nightly_timeout


@pytest.mark.medium
class DescribeLargeTierWorkflowComments:
    def it_does_not_claim_failures_notify_the_repository_watchers(self) -> None:
        text = (WORKFLOWS_DIR / 'large-tier.yml').read_text(encoding='utf-8')

        assert "repository's watchers" not in text

    @pytest.mark.parametrize('workflow_name', ['large-tier.yml', 'ci.yml', 'release.yml'])
    def it_records_that_the_large_tier_runs_on_ubuntu_only(self, workflow_name: str) -> None:
        text = (WORKFLOWS_DIR / workflow_name).read_text(encoding='utf-8')

        assert 'large tier runs on ubuntu only' in text.lower()

    @pytest.mark.parametrize('workflow_name', ['large-tier.yml', 'release.yml'])
    def it_documents_that_the_attrs_full_test_skips_in_the_large_tier_jobs(self, workflow_name: str) -> None:
        text = (WORKFLOWS_DIR / workflow_name).read_text(encoding='utf-8')

        assert 'test_attrs_full skips' in text
