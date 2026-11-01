"""Structural tests for .github/workflows/ci.yml so GitHub's merge queue can run the required checks.

The merge queue tests each PR on a temporary branch and fires the ``merge_group`` event. A required check that
does not run on that event never reports, and the queued PR times out.
"""

from __future__ import annotations

from pathlib import Path
from typing import (
    Any,
    cast,
)

import pytest
import yaml

CI_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'ci.yml'
AGGREGATE_JOB = 'all-checks'
AGGREGATE_JOB_NAME = 'All Checks Passed'
PR_ONLY_CONTEXTS = ('github.event.pull_request', 'github.head_ref', 'github.base_ref')


def _workflow() -> dict[Any, Any]:
    return cast('dict[Any, Any]', yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8')))


def _triggers() -> dict[str, Any]:
    # PyYAML parses the bare key ``on`` as boolean True.
    workflow = _workflow()
    return cast('dict[str, Any]', workflow.get('on', workflow.get(True)))


@pytest.mark.medium
class DescribeCiMergeGroupTrigger:
    def it_triggers_on_merge_group(self) -> None:
        assert 'merge_group' in _triggers()

    def it_keeps_the_push_and_pull_request_triggers_on_main(self) -> None:
        triggers = _triggers()

        assert triggers['push'] == {'branches': ['main']}
        assert triggers['pull_request'] == {'branches': ['main']}

    def it_makes_the_aggregate_job_need_every_other_job(self) -> None:
        jobs = _workflow()['jobs']
        other_jobs = set(jobs) - {AGGREGATE_JOB}

        assert set(jobs[AGGREGATE_JOB]['needs']) == other_jobs

    def it_runs_the_aggregate_job_even_when_a_needed_job_fails(self) -> None:
        assert _workflow()['jobs'][AGGREGATE_JOB]['if'] == 'always()'

    def it_reports_the_aggregate_job_under_its_required_check_name(self) -> None:
        assert _workflow()['jobs'][AGGREGATE_JOB]['name'] == AGGREGATE_JOB_NAME

    @pytest.mark.parametrize('context', PR_ONLY_CONTEXTS)
    def it_does_not_read_pull_request_only_contexts(self, context: str) -> None:
        text = CI_WORKFLOW.read_text(encoding='utf-8')

        assert context not in text

    def it_isolates_the_concurrency_group_per_ref(self) -> None:
        # Each merge group runs on its own gh-readonly-queue ref, so a ref-keyed group never cancels another.
        assert '${{ github.ref }}' in _workflow()['concurrency']['group']
