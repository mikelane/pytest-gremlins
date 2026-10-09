"""Structural tests for .github/workflows/release.yml.

GitHub Actions gives a job whose ``if:`` has no status-check function an implicit ``success()``. That is false
when ANY job earlier in its ``needs`` chain was skipped, not only a direct need. These tests pin the workflow
shape that keeps a skipped job from silently skipping the whole release, plus the guards around tag handling,
checkout, permissions and the Test PyPI install.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

import pytest
import yaml

RELEASE_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'release.yml'

SKIP_OVERRIDING_STATUS_FUNCTIONS = ('always()', '!cancelled()')
SKIPPABLE_JOB_IDS = {'publish-test-pypi', 'verify-test-pypi'}
RELEASE_REF = '${{ env.RELEASE_REF }}'


def _workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load(RELEASE_WORKFLOW.read_text()))


def _jobs() -> dict[str, Any]:
    return dict(_workflow()['jobs'])


def _steps(job_id: str) -> list[dict[str, Any]]:
    return list(_jobs()[job_id]['steps'])


def _step_named(job_id: str, name: str) -> dict[str, Any]:
    return next(step for step in _steps(job_id) if step.get('name') == name)


def _step_index(job_id: str, predicate: Any) -> int:
    return next(index for index, step in enumerate(_steps(job_id)) if predicate(step))


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get('needs', [])
    return [needs] if isinstance(needs, str) else list(needs)


def _condition(job: dict[str, Any]) -> str:
    return str(job.get('if', ''))


def _overrides_implicit_success(job: dict[str, Any]) -> bool:
    return any(function in _condition(job) for function in SKIP_OVERRIDING_STATUS_FUNCTIONS)


def _is_skippable(job: dict[str, Any]) -> bool:
    """A job-level ``if`` with no status function skips the job (and its dependents) when false."""
    return 'if' in job and not _overrides_implicit_success(job)


def _ancestors(jobs: dict[str, Any], job_id: str) -> set[str]:
    seen: set[str] = set()
    stack = _needs(jobs[job_id])
    while stack:
        parent = stack.pop()
        if parent not in seen:
            seen.add(parent)
            stack.extend(_needs(jobs[parent]))
    return seen


def _skippable_ancestors(jobs: dict[str, Any], job_id: str) -> set[str]:
    return {parent for parent in _ancestors(jobs, job_id) if _is_skippable(jobs[parent])}


def _job_ids_below_skippable_jobs() -> list[str]:
    jobs = _jobs()
    return [job_id for job_id, job in jobs.items() if _skippable_ancestors(jobs, job_id) and not _is_skippable(job)]


def _checkout_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job['steps'] if str(step.get('uses', '')).startswith('actions/checkout')]


def _run_step(step: dict[str, Any], cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Execute a step's real ``run`` script the way a ``shell: bash`` step runs it (errexit and pipefail)."""
    return subprocess.run(
        ['bash', '-eo', 'pipefail', '-c', step['run']],  # noqa: S607
        cwd=cwd,
        env={'PATH': '/usr/bin:/bin', **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _write_fake_venv_python(root: Path, *, installed_version: str) -> None:
    interpreter = root / '.venv' / 'bin' / 'python'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(f'#!/bin/sh\necho {installed_version}\n')
    interpreter.chmod(0o755)


def _job_ids_with_checkout(*, excluding: str | None = None) -> list[str]:
    return [job_id for job_id, job in _jobs().items() if job_id != excluding and _checkout_steps(job)]


@pytest.mark.medium
class DescribeReleaseWorkflowSkipPropagation:
    def it_has_only_the_test_pypi_jobs_as_skippable_jobs(self) -> None:
        jobs = _jobs()

        skippable = {job_id for job_id, job in jobs.items() if _is_skippable(job)}

        assert skippable == SKIPPABLE_JOB_IDS

    def it_finds_the_jobs_below_the_skippable_jobs(self) -> None:
        assert set(_job_ids_below_skippable_jobs()) == {'publish-pypi', 'github-release'}

    @pytest.mark.parametrize('job_id', _job_ids_below_skippable_jobs())
    def it_checks_results_explicitly_for_every_job_below_a_skippable_job(self, job_id: str) -> None:
        jobs = _jobs()
        job = jobs[job_id]

        condition = _condition(job)

        assert _overrides_implicit_success(job), (
            f'{job_id} has an implicit success() but sits below skippable job(s) '
            f'{sorted(_skippable_ancestors(jobs, job_id))}; GitHub skips it whenever they are skipped'
        )
        assert re.search(r'needs\.[\w-]+\.result', condition), f'{job_id} must check needs.<job>.result explicitly'

    def it_runs_verify_tag_on_every_event(self) -> None:
        assert 'if' not in _jobs()['verify-tag']

    def it_does_not_gate_the_test_job_on_a_condition(self) -> None:
        assert 'if' not in _jobs()['test']

    def it_creates_the_github_release_only_after_a_successful_pypi_publish(self) -> None:
        condition = _condition(_jobs()['github-release'])

        assert '!cancelled()' in condition
        assert "needs.publish-pypi.result == 'success'" in condition


@pytest.mark.medium
class DescribeReleaseWorkflowPublishGate:
    def it_needs_exactly_the_build_and_verification_jobs(self) -> None:
        assert set(_needs(_jobs()['publish-pypi'])) == {'build', 'verify-wheel', 'verify-test-pypi'}

    @pytest.mark.parametrize(
        'clause',
        [
            '!cancelled()',
            "needs.build.result == 'success'",
            "needs.verify-wheel.result == 'success'",
            "needs.verify-test-pypi.result == 'success'",
            "needs.verify-test-pypi.result == 'skipped' && inputs.skip_test_pypi == true",
        ],
    )
    def it_gates_the_pypi_publish_on_every_required_result(self, clause: str) -> None:
        condition = ' '.join(_condition(_jobs()['publish-pypi']).split())

        assert clause in condition

    def it_skips_existing_files_when_publishing_to_production_pypi(self) -> None:
        publish_step = next(step for step in _steps('publish-pypi') if 'pypi-publish' in step.get('uses', ''))

        assert publish_step['with']['skip-existing'] is True


@pytest.mark.medium
class DescribeReleaseWorkflowCheckout:
    def it_finds_the_jobs_that_check_out_the_release(self) -> None:
        assert set(_job_ids_with_checkout(excluding='verify-tag')) == {
            'test',
            'benchmark',
            'attrs-compat',
            'build',
            'github-release',
        }

    @pytest.mark.parametrize('job_id', _job_ids_with_checkout(excluding='verify-tag'))
    def it_checks_out_the_release_ref(self, job_id: str) -> None:
        for checkout in _checkout_steps(_jobs()[job_id]):
            assert checkout['with']['ref'] == RELEASE_REF

    @pytest.mark.parametrize('job_id', _job_ids_with_checkout())
    def it_does_not_persist_credentials_in_the_checkout(self, job_id: str) -> None:
        for checkout in _checkout_steps(_jobs()[job_id]):
            assert checkout['with']['persist-credentials'] is False


@pytest.mark.medium
class DescribeReleaseWorkflowPermissions:
    def it_grants_read_only_contents_by_default(self) -> None:
        assert _workflow()['permissions'] == {'contents': 'read'}

    @pytest.mark.parametrize('job_id', ['publish-test-pypi', 'publish-pypi'])
    def it_grants_id_token_write_to_the_publishing_jobs(self, job_id: str) -> None:
        assert _jobs()[job_id]['permissions'] == {'id-token': 'write'}

    def it_grants_contents_write_to_the_github_release_job(self) -> None:
        assert _jobs()['github-release']['permissions'] == {'contents': 'write'}


@pytest.mark.medium
class DescribeReleaseWorkflowTagVerification:
    def it_passes_the_release_tag_to_every_guard_invocation_through_the_environment(self) -> None:
        guard_steps = [step for step in _steps('verify-tag') if 'verify_release_tag.py' in step.get('run', '')]

        assert len(guard_steps) == 2
        for step in guard_steps:
            assert '${{' not in step['run']
            assert '"$RELEASE_TAG"' in step['run']

    def it_fetches_the_release_tag_through_the_environment_inside_quotes(self) -> None:
        fetch_step = _step_named('verify-tag', 'Fetch release tag')

        assert '${{' not in fetch_step['run']
        assert re.search(r'"[^"]*\$RELEASE_TAG[^"]*"', fetch_step['run'])

    def it_names_the_missing_tag_when_the_fetch_fails(self) -> None:
        fetch_step = _step_named('verify-tag', 'Fetch release tag')

        assert (
            '::error::Release tag $RELEASE_TAG not found on origin. Push the tag before dispatching.'
            in (fetch_step['run'])
        )

    def it_checks_the_tag_name_before_fetching_and_the_full_guard_after(self) -> None:
        name_check = _step_index('verify-tag', lambda step: '--name-only' in step.get('run', ''))
        fetch = _step_index('verify-tag', lambda step: step.get('name') == 'Fetch release tag')
        full_guard = _step_index(
            'verify-tag',
            lambda step: 'verify_release_tag.py' in step.get('run', '') and '--name-only' not in step['run'],
        )

        assert name_check < fetch < full_guard

    def it_names_the_guard_step_verify_release_tag(self) -> None:
        assert _step_named('verify-tag', 'Verify release tag')['run'].count('verify_release_tag.py') == 1

    def it_runs_the_dispatch_from_main_check_before_anything_else(self) -> None:
        first_step = _steps('verify-tag')[0]

        assert first_step['env'] == {'EVENT_NAME': '${{ github.event_name }}', 'REF': '${{ github.ref }}'}
        assert '${{' not in first_step['run']

    def it_exits_non_zero_for_a_dispatch_that_is_not_from_main(self, tmp_path: Path) -> None:
        result = _run_step(_steps('verify-tag')[0], tmp_path, EVENT_NAME='workflow_dispatch', REF='refs/heads/feature')

        assert result.returncode != 0
        assert '::error::Refusing to release from refs/heads/feature; dispatch release.yml from main.' in result.stdout

    @pytest.mark.parametrize(
        ('event_name', 'ref'),
        [('workflow_dispatch', 'refs/heads/main'), ('push', 'refs/tags/v1.2.3')],
    )
    def it_allows_a_dispatch_from_main_and_a_tag_push(self, tmp_path: Path, event_name: str, ref: str) -> None:
        result = _run_step(_steps('verify-tag')[0], tmp_path, EVENT_NAME=event_name, REF=ref)

        assert result.returncode == 0, result.stdout


@pytest.mark.medium
class DescribeReleaseWorkflowPublishing:
    def it_serializes_runs_for_the_same_release_tag(self) -> None:
        concurrency = _workflow()['concurrency']

        assert 'inputs.tag' in concurrency['group']
        assert 'github.ref_name' in concurrency['group']
        assert concurrency['cancel-in-progress'] is False

    def it_fails_the_regression_check_step_when_the_report_pipeline_fails(self) -> None:
        regression_step = _step_named('benchmark', 'Check for regression')

        assert regression_step['shell'] == 'bash'

    def it_warns_when_the_changelog_has_no_section_for_the_version(self) -> None:
        changelog_step = _step_named('github-release', 'Extract changelog for this version')

        assert (
            '::warning::No CHANGELOG.md section found for v$VERSION; release notes fall back to a placeholder.'
            in changelog_step['run']
        )


@pytest.mark.medium
class DescribeReleaseWorkflowInstallChecks:
    def it_pins_the_test_pypi_install_to_the_release_version(self) -> None:
        install_step = _step_named('verify-test-pypi', 'Install from Test PyPI')

        assert '"pytest-gremlins==${RELEASE_TAG#v}"' in install_step['run']

    def it_exits_non_zero_when_the_test_pypi_version_differs_from_the_release_tag(self, tmp_path: Path) -> None:
        _write_fake_venv_python(tmp_path, installed_version='1.11.3')
        verify_step = _step_named('verify-test-pypi', 'Verify import and version')

        result = _run_step(verify_step, tmp_path, RELEASE_TAG='v1.12.0')

        assert result.returncode != 0
        assert '::error::Test PyPI version v1.11.3 does not match release tag v1.12.0' in result.stdout

    def it_succeeds_when_the_test_pypi_version_matches_the_release_tag(self, tmp_path: Path) -> None:
        _write_fake_venv_python(tmp_path, installed_version='1.12.0')
        verify_step = _step_named('verify-test-pypi', 'Verify import and version')

        result = _run_step(verify_step, tmp_path, RELEASE_TAG='v1.12.0')

        assert result.returncode == 0, result.stdout

    def it_names_the_wheel_version_variable_distinctly(self) -> None:
        verify_step = _step_named('verify-wheel', 'Verify import and version')

        assert 'WHEEL_VERSION=' in verify_step['run']
        assert 'VERSION=' not in verify_step['run'].replace('WHEEL_VERSION=', '')
