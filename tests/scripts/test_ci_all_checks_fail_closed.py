"""Behavioral tests for the ``all-checks`` aggregate job in .github/workflows/ci.yml.

The job must fail closed: when ``Detect Changes`` does not succeed, its outputs are empty and every gated check
looks skipped, so the job has to reject the run itself instead of reporting success (issue #848).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

CI_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'ci.yml'
AGGREGATE_JOB = 'all-checks'
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == 'win32',
    reason='the step runs in bash on ubuntu-latest; Windows bash (WSL/Git Bash) does not get the minimal env',
)
CHECK_RESULT_VARIABLES = (
    'LINT_RESULT',
    'TYPECHECK_RESULT',
    'TEST_RESULT',
    'PYTEST_COMPAT_RESULT',
    'DOCS_RESULT',
    'SECURITY_RESULT',
    'ATTRS_SMOKE_RESULT',
    'VERDICT_CHANGES_RESULT',
)


def _verify_step() -> dict[str, Any]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))
    steps = workflow['jobs'][AGGREGATE_JOB]['steps']
    return next(step for step in steps if step['name'] == 'Verify all jobs succeeded')


def _run_verify_script(
    *,
    changes_result: str,
    src: str,
    docs: str,
    check_result: str,
    event_name: str = 'push',
    release_pr_result: str = 'skipped',
) -> int:
    environment = {
        'EVENT_NAME': event_name,
        'RELEASE_PR_RESULT': release_pr_result,
        'SRC_CHANGED': src,
        'DOCS_CHANGED': docs,
        'CHANGES_RESULT': changes_result,
        **dict.fromkeys(CHECK_RESULT_VARIABLES, check_result),
    }
    completed = subprocess.run(
        ['bash', '-c', _verify_step()['run']],  # noqa: S607
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


@pytest.mark.medium
@POSIX_ONLY
class DescribeAllChecksFailClosed:
    def it_passes_the_changes_result_to_the_script(self) -> None:
        assert _verify_step()['env']['CHANGES_RESULT'] == '${{ needs.changes.result }}'

    @pytest.mark.parametrize('changes_result', ['failure', 'cancelled', 'skipped'])
    def it_fails_when_detect_changes_did_not_succeed(self, changes_result: str) -> None:
        exit_code = _run_verify_script(changes_result=changes_result, src='', docs='', check_result='skipped')

        assert exit_code == 1

    def it_passes_when_changes_succeeded_and_no_gated_job_was_needed(self) -> None:
        exit_code = _run_verify_script(changes_result='success', src='false', docs='false', check_result='skipped')

        assert exit_code == 0

    def it_passes_when_changes_succeeded_and_every_gated_job_succeeded(self) -> None:
        exit_code = _run_verify_script(changes_result='success', src='true', docs='true', check_result='success')

        assert exit_code == 0

    def it_still_fails_when_a_gated_job_failed(self) -> None:
        exit_code = _run_verify_script(changes_result='success', src='true', docs='true', check_result='failure')

        assert exit_code == 1

    @pytest.mark.parametrize('release_pr_result', ['failure', 'cancelled', 'skipped'])
    def it_fails_a_pull_request_unless_the_release_pr_gates_succeeded(self, release_pr_result: str) -> None:
        exit_code = _run_verify_script(
            changes_result='success',
            src='false',
            docs='false',
            check_result='skipped',
            event_name='pull_request',
            release_pr_result=release_pr_result,
        )

        assert exit_code == 1

    def it_passes_a_pull_request_when_the_release_pr_gates_succeeded(self) -> None:
        exit_code = _run_verify_script(
            changes_result='success',
            src='false',
            docs='false',
            check_result='skipped',
            event_name='pull_request',
            release_pr_result='success',
        )

        assert exit_code == 0

    @pytest.mark.parametrize('event_name', ['push', 'merge_group'])
    def it_accepts_a_skipped_release_pr_job_off_pull_requests(self, event_name: str) -> None:
        exit_code = _run_verify_script(
            changes_result='success',
            src='false',
            docs='false',
            check_result='skipped',
            event_name=event_name,
            release_pr_result='skipped',
        )

        assert exit_code == 0

    def it_passes_the_event_name_and_release_pr_result_to_the_script(self) -> None:
        env = _verify_step()['env']

        assert env['EVENT_NAME'] == '${{ github.event_name }}'
        assert env['RELEASE_PR_RESULT'] == '${{ needs.release-pr.result }}'


def _release_pr_job() -> dict[str, Any]:
    job: dict[str, Any] = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))['jobs']['release-pr']
    return job


def _release_pr_step(fragment: str) -> dict[str, Any]:
    return next(step for step in _release_pr_job()['steps'] if fragment in step.get('run', ''))


@pytest.mark.medium
class DescribeReleasePrJob:
    def it_runs_only_on_pull_requests_with_no_changes_filter(self) -> None:
        job = _release_pr_job()

        assert job['if'] == "github.event_name == 'pull_request'"
        assert 'needs' not in job

    def it_is_needed_by_the_aggregate_job(self) -> None:
        assert 'release-pr' in yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))['jobs'][AGGREGATE_JOB]['needs']

    def it_grants_the_job_read_only_permissions_because_it_runs_pull_request_code(self) -> None:
        assert _release_pr_job()['permissions'] == {'contents': 'read'}

    def it_checks_out_full_history_for_the_cache_gate(self) -> None:
        checkout = next(step for step in _release_pr_job()['steps'] if 'actions/checkout' in step.get('uses', ''))

        assert checkout['with']['fetch-depth'] == 0

    def it_does_not_persist_the_checkout_token(self) -> None:
        checkout = next(step for step in _release_pr_job()['steps'] if 'actions/checkout' in step.get('uses', ''))

        assert checkout['with']['persist-credentials'] is False

    def it_never_interpolates_expressions_into_shell_scripts(self) -> None:
        run_scripts = [step['run'] for step in _release_pr_job()['steps'] if 'run' in step]

        assert [script for script in run_scripts if '${{' in script] == []

    def it_passes_the_branch_and_default_branch_through_the_environment(self) -> None:
        env = _release_pr_step('check_version_change.py')['env']

        assert env['HEAD_REF'] == '${{ github.head_ref }}'
        assert env['DEFAULT_BRANCH'] == '${{ github.event.repository.default_branch }}'

    def it_runs_the_guard_unconditionally(self) -> None:
        assert 'if' not in _release_pr_step('check_version_change.py')

    def it_publishes_the_guard_outputs_under_the_step_id_the_gates_read(self) -> None:
        # Without --github-output or id: guard, version_changed is never 'true' and every gate silently skips.
        guard_step = _release_pr_step('check_version_change.py')

        assert guard_step['id'] == 'guard'
        assert '--github-output "$GITHUB_OUTPUT"' in guard_step['run']

    def it_takes_the_merge_base_with_the_remote_default_branch(self) -> None:
        assert '--base-ref "origin/$DEFAULT_BRANCH"' in _release_pr_step('check_version_change.py')['run']

    @pytest.mark.parametrize(
        'script',
        [
            'mkdocs build',
            'scripts/check_release_docs.py',
            'check_cache_kept.py',
            'check_cache_bump.py',
            'check_no_wip_tests.py',
        ],
    )
    def it_runs_the_release_gates_only_when_the_version_changed(self, script: str) -> None:
        assert _release_pr_step(script)['if'] == "steps.guard.outputs.version_changed == 'true'"

    @pytest.mark.parametrize('script', ['scripts/check_release_docs.py', 'check_cache_kept.py', 'check_cache_bump.py'])
    def it_passes_the_version_to_the_gates_through_the_environment(self, script: str) -> None:
        step = _release_pr_step(script)

        assert step['env']['VERSION'] == '${{ steps.guard.outputs.version }}'
        assert '"$VERSION"' in step['run']

    def it_runs_the_gates_cheapest_first(self) -> None:
        commands = [step['run'] for step in _release_pr_job()['steps'] if 'check_' in step.get('run', '')]
        gate_order = [
            next(
                name for name in ('version_change', 'release_docs', 'cache_kept', 'cache_bump', 'no_wip') if name in run
            )
            for run in commands
        ]

        assert gate_order == ['version_change', 'release_docs', 'cache_kept', 'cache_bump', 'no_wip']

    def it_has_no_bypass_input(self) -> None:
        text = CI_WORKFLOW.read_text(encoding='utf-8')

        assert 'workflow_dispatch' not in text
