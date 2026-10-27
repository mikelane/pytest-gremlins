"""Behavioral tests for the ``all-checks`` aggregate job in .github/workflows/ci.yml.

The job must fail closed: when ``Detect Changes`` does not succeed, its outputs are empty and every gated check
looks skipped, so the job has to reject the run itself instead of reporting success (issue #848).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest
import yaml

CI_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'ci.yml'
AGGREGATE_JOB = 'all-checks'
CHECK_RESULT_VARIABLES = (
    'LINT_RESULT',
    'TYPECHECK_RESULT',
    'TEST_RESULT',
    'PYTEST_COMPAT_RESULT',
    'DOCS_RESULT',
    'SECURITY_RESULT',
    'ATTRS_SMOKE_RESULT',
)


def _verify_step() -> dict[str, Any]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))
    steps = workflow['jobs'][AGGREGATE_JOB]['steps']
    return next(step for step in steps if step['name'] == 'Verify all jobs succeeded')


def _run_verify_script(*, changes_result: str, src: str, docs: str, check_result: str) -> int:
    environment = {
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
