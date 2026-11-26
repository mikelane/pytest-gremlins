"""Structural tests for .github/workflows/tag-release.yml, the workflow that tags and dispatches a release (#1046).

The workflow stays thin: one checkout and one step that runs scripts/tag_release.py, which holds the logic (and has its
own tests). These tests pin what the workflow may be triggered by, which privileges it holds, that the tagging token
reaches only the script, and that no ``${{ }}`` expression is interpolated into a shell script.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'tag-release.yml'
CHECKOUT_PIN = 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'
RELEASE_WORKFLOW = WORKFLOW.with_name('release.yml')
SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
JOB_PERMISSIONS = {'contents': 'write', 'actions': 'write', 'issues': 'read', 'pull-requests': 'read'}
EXPORTED_SCRIPTS = (
    'tag_release.py',
    'check_no_release_blockers.py',
    'check_ci_passed.py',
    'check_version_change.py',
    'check_release_docs.py',
)
FORBIDDEN_COMMANDS = (
    re.compile(r'\bgit\b[^\n|;&]*\stag(?![\w.=-])'),
    re.compile(r'\bgit\b[^\n|;&]*\spush(?![\w.=-])'),
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


def _checkout() -> dict[str, Any]:
    return next(step for step in _steps() if str(step.get('uses', '')).startswith('actions/checkout'))


def _script_step() -> dict[str, Any]:
    return next(step for step in _steps() if 'SCRIPTS_DIR/tag_release.py' in str(step.get('run', '')))


def _local_imports(script: Path) -> set[str]:
    tree = ast.parse(script.read_text())
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    return {f'{name}.py' for name in names if (SCRIPTS / f'{name}.py').is_file()}


def _script_closure() -> set[str]:
    # tag_release.py, the sibling scripts it runs (named as string literals), and everything they import from scripts/.
    entry = SCRIPTS / 'tag_release.py'
    pending = {'tag_release.py'} | {
        name for name in re.findall(r"'(\w+\.py)'", entry.read_text()) if (SCRIPTS / name).is_file()
    }
    closure: set[str] = set()
    while pending:
        name = pending.pop()
        closure.add(name)
        pending |= _local_imports(SCRIPTS / name) - closure
    return closure


def _join_continuations(script: str) -> str:
    return re.sub(r'\\\r?\n\s*', ' ', script)


def _run_blocks() -> list[str]:
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
class DescribeTheRetiredDryRun:
    def it_has_no_dry_run_constant(self) -> None:
        assert 'DRY_RUN' not in WORKFLOW.read_text()
        assert 'env' not in _workflow()

    def it_no_longer_runs_the_announce_script(self) -> None:
        assert 'announce_untagged_release' not in WORKFLOW.read_text()


@pytest.mark.medium
class DescribeThePrivileges:
    def it_grants_only_contents_read_at_the_workflow_level(self) -> None:
        assert _workflow()['permissions'] == {'contents': 'read'}

    def it_grants_the_job_exactly_what_tagging_and_dispatching_need(self) -> None:
        assert [job['permissions'] for job in _jobs().values()] == [JOB_PERMISSIONS]

    def it_has_one_job(self) -> None:
        assert len(_jobs()) == 1

    def it_uses_no_personal_access_token(self) -> None:
        assert 'secrets.' not in WORKFLOW.read_text()

    def it_does_not_persist_checkout_credentials(self) -> None:
        assert _checkout()['with']['persist-credentials'] is False

    def it_gives_the_workflow_token_only_to_the_script_step(self) -> None:
        token_carrying_steps = [
            step for step in _steps() if 'GH_TOKEN' in step.get('env', {}) or 'GITHUB_TOKEN' in step.get('env', {})
        ]

        assert token_carrying_steps == [_script_step()]
        assert _script_step()['env']['GH_TOKEN'] == '${{ github.token }}'  # noqa: S105
        assert _script_step()['env']['GITHUB_TOKEN'] == '${{ github.token }}'  # noqa: S105


@pytest.mark.medium
class DescribeTheScriptStep:
    def it_fetches_the_pushed_commit_and_its_parent(self) -> None:
        assert _checkout()['with']['fetch-depth'] == 2

    def it_passes_the_pushed_commit_through_the_environment(self) -> None:
        assert _script_step()['env']['SHA'] == '${{ github.sha }}'
        assert '--sha "$SHA"' in _script_step()['run']

    def it_runs_the_exported_script_with_the_system_python_from_outside_the_workspace(self) -> None:
        run = _script_step()['run']

        assert re.search(r'^cd "\$RUNNER_TEMP"$', run, re.MULTILINE)
        assert '/usr/bin/python3 -I "$SCRIPTS_DIR/tag_release.py"' in run

    def it_exports_the_scripts_it_runs_from_the_parent_commit_in_an_earlier_step(self) -> None:
        steps = _steps()
        export = next(step for step in steps if 'git show' in str(step.get('run', '')))

        assert steps.index(export) < steps.index(_script_step())
        assert export['env']['BEFORE'] == '${{ github.event.before }}'
        assert [script for script in EXPORTED_SCRIPTS if script not in export['run']] == []
        assert '"$BEFORE:scripts/$script"' in export['run']
        assert 'exit 2' in export['run']
        assert export['id'] == 'export'
        assert _script_step()['env']['SCRIPTS_DIR'] == '${{ steps.export.outputs.dir }}'

    def it_exports_exactly_the_scripts_tag_release_runs_and_their_local_imports(self) -> None:
        # A gate that gains a sibling import would otherwise fail with ImportError on the first real release.
        assert set(EXPORTED_SCRIPTS) == _script_closure()

    def it_fails_closed_unless_before_is_a_commit_in_the_checkout(self) -> None:
        run = next(step for step in _steps() if step.get('id') == 'export')['run']

        assert '[ -z "$BEFORE" ]' in run
        assert '0000000000000000000000000000000000000000' in run
        assert 'cat-file -e "$BEFORE^{commit}"' in run
        assert run.count('exit 2') >= 3

    def it_passes_before_to_the_script(self) -> None:
        assert _script_step()['env']['BEFORE'] == '${{ github.event.before }}'
        assert '--before "$BEFORE"' in _script_step()['run']

    def it_runs_no_script_from_the_workspace(self) -> None:
        # The pushed commit may have edited anything under scripts/; only the parent's copies may run.
        remainders = [
            re.sub(r'"\$BEFORE:scripts/\$script"', '', script).replace('$RUNNER_TEMP', '') for script in _run_blocks()
        ]

        assert not any('scripts/' in remainder for remainder in remainders)

    def it_does_not_install_python_or_uv(self) -> None:
        assert not any(
            'uv' in str(step.get('uses', '')) or 'uv python' in str(step.get('run', '')) for step in _steps()
        )


@pytest.mark.medium
class DescribeAThinWorkflow:
    @pytest.mark.parametrize('command', FORBIDDEN_COMMANDS, ids=lambda pattern: pattern.pattern)
    def it_runs_no_tagging_or_dispatching_command_itself(self, command: re.Pattern[str]) -> None:
        assert not any(command.search(script) for script in _run_blocks())

    def it_interpolates_no_expression_into_a_shell_script(self) -> None:
        assert not any('${{' in str(step['run']) for step in _steps() if 'run' in step)

    def it_does_not_read_the_version_with_grep(self) -> None:
        assert not any(re.search(r'\b(?:grep|sed|awk)\b', script) for script in _run_blocks())


@pytest.mark.medium
class DescribeTheConcurrencyGroup:
    def it_serializes_runs_without_cancelling_one_in_progress(self) -> None:
        concurrency = _workflow()['concurrency']

        assert concurrency['cancel-in-progress'] is False
        assert concurrency['group'] == 'tag-release'


@pytest.mark.medium
class DescribeActionPins:
    def it_pins_checkout_to_the_same_sha_as_release(self) -> None:
        assert _checkout()['uses'] == CHECKOUT_PIN
        assert CHECKOUT_PIN in RELEASE_WORKFLOW.read_text()

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

    @pytest.mark.parametrize(
        'script',
        [
            '(cd dist && git push)',
            'git push; echo pushed',
            "bash -c 'git push'",
            'git tag|| exit 1',
        ],
    )
    def it_catches_a_bare_subcommand_followed_by_shell_punctuation(self, script: str) -> None:
        assert _is_forbidden(script)
