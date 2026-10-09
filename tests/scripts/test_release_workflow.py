"""Structural tests for .github/workflows/release.yml.

GitHub Actions gives a job whose ``if:`` has no status-check function an implicit ``success()``. That is false
when ANY job earlier in its ``needs`` chain was skipped, not only a direct need. These tests pin the workflow
shape that keeps a skipped job from silently skipping the whole release.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

RELEASE_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'release.yml'

STATUS_FUNCTIONS = ('always()', '!cancelled()')
SKIPPABLE_BY_DESIGN = {'publish-test-pypi', 'verify-test-pypi'}


def _workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load(RELEASE_WORKFLOW.read_text()))


def _jobs() -> dict[str, Any]:
    return dict(_workflow()['jobs'])


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get('needs', [])
    return [needs] if isinstance(needs, str) else list(needs)


def _condition(job: dict[str, Any]) -> str:
    return str(job.get('if', ''))


def _has_status_check(job: dict[str, Any]) -> bool:
    return any(function in _condition(job) for function in STATUS_FUNCTIONS)


def _is_skippable(job: dict[str, Any]) -> bool:
    """A job-level ``if`` with no status function skips the job (and its dependents) when false."""
    return 'if' in job and not _has_status_check(job)


def _ancestors(jobs: dict[str, Any], name: str) -> set[str]:
    seen: set[str] = set()
    stack = _needs(jobs[name])
    while stack:
        parent = stack.pop()
        if parent not in seen:
            seen.add(parent)
            stack.extend(_needs(jobs[parent]))
    return seen


def _skippable_ancestors(jobs: dict[str, Any], name: str) -> set[str]:
    return {parent for parent in _ancestors(jobs, name) if _is_skippable(jobs[parent])}


def _jobs_below_skippable_jobs() -> list[str]:
    jobs = _jobs()
    return [name for name, job in jobs.items() if _skippable_ancestors(jobs, name) and not _is_skippable(job)]


@pytest.mark.medium
class DescribeReleaseWorkflowSkipPropagation:
    def it_has_only_the_test_pypi_jobs_as_skippable_jobs(self) -> None:
        jobs = _jobs()

        skippable = {name for name, job in jobs.items() if _is_skippable(job)}

        assert skippable == SKIPPABLE_BY_DESIGN

    @pytest.mark.parametrize('job_name', _jobs_below_skippable_jobs())
    def it_checks_results_explicitly_for_every_job_below_a_skippable_job(self, job_name: str) -> None:
        jobs = _jobs()
        job = jobs[job_name]

        condition = _condition(job)

        assert _has_status_check(job), (
            f'{job_name} has an implicit success() but sits below skippable job(s) '
            f'{sorted(_skippable_ancestors(jobs, job_name))}; GitHub skips it whenever they are skipped'
        )
        assert re.search(r'needs\.[\w-]+\.result', condition), f'{job_name} must check needs.<job>.result explicitly'

    def it_runs_verify_tag_on_every_event(self) -> None:
        assert 'if' not in _jobs()['verify-tag']

    def it_does_not_gate_the_test_job_on_a_condition(self) -> None:
        assert 'if' not in _jobs()['test']

    def it_creates_the_github_release_only_after_a_successful_pypi_publish(self) -> None:
        condition = _condition(_jobs()['github-release'])

        assert '!cancelled()' in condition
        assert "needs.publish-pypi.result == 'success'" in condition


@pytest.mark.medium
class DescribeReleaseWorkflowTagVerification:
    def it_passes_the_release_tag_to_the_guard_through_the_environment(self) -> None:
        steps = _jobs()['verify-tag']['steps']
        guard_step = next(step for step in steps if 'verify_release_tag.py' in step.get('run', ''))

        assert '${{' not in guard_step['run']
        assert guard_step['run'].count('"$RELEASE_TAG"') >= 1

    def it_fetches_the_release_tag_before_running_the_guard(self) -> None:
        steps = _jobs()['verify-tag']['steps']
        runs = [step.get('run', '') for step in steps]
        fetch_index = next(i for i, run in enumerate(runs) if 'git fetch' in run and 'refs/tags/$RELEASE_TAG' in run)
        guard_index = next(i for i, run in enumerate(runs) if 'verify_release_tag.py' in run)

        assert fetch_index < guard_index


@pytest.mark.medium
class DescribeReleaseWorkflowPublishing:
    def it_serializes_runs_for_the_same_release_tag(self) -> None:
        concurrency = _workflow()['concurrency']

        assert 'inputs.tag' in concurrency['group']
        assert 'github.ref_name' in concurrency['group']
        assert concurrency['cancel-in-progress'] is False

    def it_skips_existing_files_when_publishing_to_production_pypi(self) -> None:
        steps = _jobs()['publish-pypi']['steps']
        publish_step = next(step for step in steps if 'pypi-publish' in step.get('uses', ''))

        assert publish_step['with']['skip-existing'] is True
