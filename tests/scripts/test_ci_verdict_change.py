"""Structural and behavioral tests for the verdict-change jobs in .github/workflows/ci.yml (#876).

``verdict-changes`` lists the changed paths the cache-version guard covers. ``verdict-change`` runs only when it
found one, and ``All Checks Passed`` requires it then, and only then, so a PR that touches no guarded path sees
the check skipped rather than failed.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

CI_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'ci.yml'
DETECT_JOB = 'verdict-changes'
CHECK_JOB = 'verdict-change'
AGGREGATE_JOB = 'all-checks'
SCRIPT = 'scripts/check_verdict_change.py'
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == 'win32',
    reason='the step runs in bash on ubuntu-latest; Windows bash (WSL/Git Bash) does not get the minimal env',
)


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))['jobs']


def _step_commands(job: str) -> str:
    return '\n'.join(step.get('run', '') for step in _jobs()[job]['steps'])


def _verify_script() -> str:
    steps = _jobs()[AGGREGATE_JOB]['steps']
    return next(step for step in steps if step['name'] == 'Verify all jobs succeeded')['run']


def _run_verify_script(*, guarded: str, detect_result: str, check_result: str) -> int:
    environment = {
        'CHANGES_RESULT': 'success',
        'SRC_CHANGED': 'true',
        'DOCS_CHANGED': 'false',
        'LINT_RESULT': 'success',
        'TYPECHECK_RESULT': 'success',
        'TEST_RESULT': 'success',
        'PYTEST_COMPAT_RESULT': 'success',
        'DOCS_RESULT': 'success',
        'SECURITY_RESULT': 'success',
        'ATTRS_SMOKE_RESULT': 'success',
        'VERDICT_CHANGES_RESULT': detect_result,
        'VERDICT_GUARDED': guarded,
        'VERDICT_CHANGE_RESULT': check_result,
    }
    completed = subprocess.run(
        ['bash', '-c', _verify_script()],  # noqa: S607
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


@pytest.mark.medium
class DescribeVerdictChangeJobs:
    def it_looks_for_guarded_changes_only_when_source_changed(self) -> None:
        assert _jobs()[DETECT_JOB]['if'] == "needs.changes.outputs.src == 'true'"

    def it_lists_guarded_changes_with_the_guard_file_set(self) -> None:
        assert f'{SCRIPT} guarded-changes' in _step_commands(DETECT_JOB)

    def it_runs_the_check_only_when_a_guarded_path_changed(self) -> None:
        assert _jobs()[CHECK_JOB]['if'] == f"needs.{DETECT_JOB}.outputs.guarded == 'true'"

    def it_runs_the_sample_twice_and_compares_the_verdicts(self) -> None:
        commands = _step_commands(CHECK_JOB)

        assert (commands.count(f'{SCRIPT} run'), f'{SCRIPT} compare' in commands) == (2, True)

    def it_disables_the_gremlin_cache_for_both_runs(self) -> None:
        assert '--gremlin-cache' not in _step_commands(CHECK_JOB)


@pytest.mark.medium
@POSIX_ONLY
class DescribeAllChecksRequiresTheVerdictCheck:
    def it_fails_when_a_guarded_path_changed_and_the_check_failed(self) -> None:
        assert _run_verify_script(guarded='true', detect_result='success', check_result='failure') == 1

    def it_passes_when_a_guarded_path_changed_and_the_check_passed(self) -> None:
        assert _run_verify_script(guarded='true', detect_result='success', check_result='success') == 0

    def it_passes_when_no_guarded_path_changed_and_the_check_was_skipped(self) -> None:
        assert _run_verify_script(guarded='false', detect_result='success', check_result='skipped') == 0

    def it_fails_when_source_changed_and_the_guarded_path_detection_failed(self) -> None:
        assert _run_verify_script(guarded='', detect_result='failure', check_result='skipped') == 1
