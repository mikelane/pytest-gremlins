"""Structural tests for .github/workflows/tag-release.yml, the dry-run tagging workflow (#1045).

The workflow only reports which tag it would create. These tests pin that it cannot do more: no trigger other than a
push to main, read-only permissions, no secrets and no step that tags, pushes or dispatches. Phase #1046 flips it to
the real thing and replaces the "cannot tag" tests with their live counterparts.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'tag-release.yml'
CHECKOUT_PIN = 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
CUT_RELEASE_WORKFLOW = WORKFLOW.with_name('cut-release.yml')
FORBIDDEN_COMMANDS = (
    re.compile(r'\bgit\b[^\n|;&]*\stag(?=\s|$)'),
    re.compile(r'\bgit\b[^\n|;&]*\spush(?=\s|$)'),
    re.compile(r'\bgh\s+workflow\b'),
    re.compile(r'\bgh\s+api\b'),
    re.compile(r'\bgh\s+release\b'),
)


def _workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text()))


def _triggers() -> Any:
    # PyYAML (YAML 1.1) loads the bare key ``on`` as the boolean True.
    workflow = _workflow()
    return workflow['on'] if 'on' in workflow else workflow[True]


def _jobs() -> dict[str, Any]:
    return dict(_workflow()['jobs'])


def _steps() -> list[dict[str, Any]]:
    return [step for job in _jobs().values() for step in job['steps']]


def _join_continuations(script: str) -> str:
    return re.sub(r'\\\r?\n\s*', ' ', script)


def _run_scripts() -> list[str]:
    return [_join_continuations(str(step['run'])) for step in _steps() if 'run' in step]


def _is_forbidden(script: str) -> bool:
    joined = _join_continuations(script)
    return any(re.search(pattern, joined) for pattern in FORBIDDEN_COMMANDS)


@pytest.mark.medium
class DescribeTheTrigger:
    def it_runs_only_on_a_push(self) -> None:
        assert set(_triggers()) == {'push'}

    def it_runs_only_for_the_main_branch(self) -> None:
        assert _triggers()['push'] == {'branches': ['main']}

    def it_has_no_workflow_dispatch_or_inputs(self) -> None:
        text = WORKFLOW.read_text()

        assert 'workflow_dispatch' not in text
        assert 'inputs' not in text

    def it_has_no_paths_filter(self) -> None:
        assert 'paths' not in _triggers()['push']
        assert 'paths-ignore' not in _triggers()['push']


@pytest.mark.medium
class DescribeTheDryRunSwitch:
    def it_sets_the_dry_run_constant_to_true_for_the_whole_workflow(self) -> None:
        assert _workflow()['env']['DRY_RUN'] == 'true'


@pytest.mark.medium
class DescribeThePrivileges:
    def it_grants_only_contents_read_at_the_workflow_level(self) -> None:
        assert _workflow()['permissions'] == {'contents': 'read'}

    def it_grants_nothing_more_to_any_job(self) -> None:
        assert all(job.get('permissions', {'contents': 'read'}) == {'contents': 'read'} for job in _jobs().values())

    def it_references_no_secrets(self) -> None:
        assert 'secrets.' not in WORKFLOW.read_text()
        assert 'RELEASE_PAT' not in WORKFLOW.read_text()

    def it_does_not_persist_checkout_credentials(self) -> None:
        checkout = next(step for step in _steps() if str(step.get('uses', '')).startswith('actions/checkout'))

        assert checkout['with']['persist-credentials'] is False


@pytest.mark.medium
class DescribeWhatTheWorkflowCannotDo:
    @pytest.mark.parametrize('command', FORBIDDEN_COMMANDS, ids=lambda pattern: pattern.pattern)
    def it_runs_no_command_that_tags_pushes_or_dispatches(self, command: re.Pattern[str]) -> None:
        assert not any(command.search(script) for script in _run_scripts())

    def it_never_dispatches_the_release_workflow(self) -> None:
        assert 'release.yml' not in WORKFLOW.read_text()


@pytest.mark.medium
class DescribeTheRemoteLookup:
    def it_checks_out_with_a_shallow_default_clone(self) -> None:
        checkout = next(step for step in _steps() if str(step.get('uses', '')).startswith('actions/checkout'))

        assert 'fetch-depth' not in checkout.get('with', {})

    def it_runs_the_announce_script_with_the_pushed_commit(self) -> None:
        announce_step = next(step for step in _steps() if 'announce_untagged_release.py' in str(step.get('run', '')))

        assert announce_step['env']['SHA'] == '${{ github.sha }}'
        assert '--sha "$SHA"' in announce_step['run']

    def it_does_not_read_the_version_with_grep(self) -> None:
        assert not any(re.search(r'\b(?:grep|sed|awk)\b', script) for script in _run_scripts())


@pytest.mark.medium
class DescribeTheConcurrencyGroup:
    def it_serializes_runs_without_cancelling_one_in_progress(self) -> None:
        concurrency = _workflow()['concurrency']

        assert concurrency['cancel-in-progress'] is False
        assert concurrency['group'] == 'tag-release'


@pytest.mark.medium
class DescribeActionPins:
    def it_pins_checkout_to_the_same_sha_as_cut_release(self) -> None:
        checkout = next(step for step in _steps() if str(step.get('uses', '')).startswith('actions/checkout'))

        assert checkout['uses'] == CHECKOUT_PIN
        assert CHECKOUT_PIN in CUT_RELEASE_WORKFLOW.read_text()

    def it_pins_every_action_to_a_full_commit_sha(self) -> None:
        action_references = [str(step['uses']) for step in _steps() if 'uses' in step]

        assert action_references
        assert all(re.search(r'@[0-9a-f]{40}$', reference) for reference in action_references)


@pytest.mark.small
class DescribeTheForbiddenCommandPatterns:
    @pytest.mark.parametrize(
        'script',
        [
            'git -C . push origin v1.2.3',
            'git -c user.name=bot tag -a v1.2.3 -m release',
            'git --git-dir=.git -C . tag v1.2.3',
        ],
    )
    def it_catches_a_git_command_with_a_valued_global_option(self, script: str) -> None:
        assert _is_forbidden(script)

    @pytest.mark.parametrize(
        'script',
        [
            'git -C . \\\n  push origin v1.2.3',
            'git \\\n  tag -a v1.2.3 -m release',
        ],
    )
    def it_catches_a_git_command_split_by_a_line_continuation(self, script: str) -> None:
        assert _is_forbidden(script)

    def it_does_not_flag_a_tag_config_key_as_a_tag_command(self) -> None:
        assert not _is_forbidden('git -c tag.gpgSign=false commit -m release')
