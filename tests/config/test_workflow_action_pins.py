"""Every non-local ``uses:`` in a workflow pins a full commit SHA, with the release tag in a trailing comment.

A moved or compromised tag would otherwise run new code with the job's token and secrets.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
DEPENDABOT_PATH = REPO_ROOT / '.github' / 'dependabot.yml'

USES_LINE = re.compile(r'^\s*(?:-\s+)?(?:\{(?:[^}#]*,\s*)?)?uses:\s*(?P<ref>[^\s,}]+)(?P<rest>.*)$')
PINNED_REF = re.compile(r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$')
TAG_COMMENT = re.compile(r'^\s+#\s*v?\d[\w.+-]*\s*$')


def _workflow_files(directory: Path) -> list[Path]:
    return sorted([*directory.glob('*.yml'), *directory.glob('*.yaml')])


def _external_uses(directory: Path = WORKFLOWS_DIR) -> list[tuple[str, int, str, str]]:
    found = []
    for workflow in _workflow_files(directory):
        for number, line in enumerate(workflow.read_text(encoding='utf-8').splitlines(), start=1):
            match = USES_LINE.match(line)
            if match and not match['ref'].startswith('./'):
                found.append((workflow.name, number, match['ref'], match['rest']))
    return found


def _dependabot_watches_github_actions(text: str) -> bool:
    updates = yaml.safe_load(text).get('updates', [])
    return any(entry.get('package-ecosystem') == 'github-actions' for entry in updates)


@pytest.mark.medium
class DescribeWorkflowActionPins:
    def it_finds_external_actions_to_check(self) -> None:
        assert len(_external_uses()) > 0

    @pytest.mark.parametrize(('workflow', 'number', 'ref'), [use[:3] for use in _external_uses()])
    def it_pins_each_action_to_a_full_commit_sha(self, workflow: str, number: int, ref: str) -> None:
        assert PINNED_REF.match(ref), f'{workflow}:{number} uses {ref}, which is not pinned to a 40-character SHA'

    @pytest.mark.parametrize(('workflow', 'number', 'ref', 'rest'), _external_uses())
    def it_records_the_release_tag_in_a_trailing_comment(self, workflow: str, number: int, ref: str, rest: str) -> None:
        assert TAG_COMMENT.match(rest), f'{workflow}:{number} uses {ref} without a trailing "# vX.Y.Z" tag comment'

    def it_keeps_dependabot_watching_github_actions(self) -> None:
        assert _dependabot_watches_github_actions(DEPENDABOT_PATH.read_text(encoding='utf-8'))

    def it_flags_a_commented_out_dependabot_actions_entry(self) -> None:
        commented = 'version: 2\nupdates:\n  # - package-ecosystem: github-actions\n  - package-ecosystem: pip\n'

        assert not _dependabot_watches_github_actions(commented)

    def it_checks_dot_yaml_workflows(self, tmp_path: Path) -> None:
        (tmp_path / 'extra.yaml').write_text('steps:\n  - uses: actions/checkout@v7\n', encoding='utf-8')

        assert [use[2] for use in _external_uses(tmp_path)] == ['actions/checkout@v7']

    def it_checks_flow_mapping_steps(self, tmp_path: Path) -> None:
        (tmp_path / 'extra.yml').write_text('steps:\n  - {uses: actions/checkout@v7}\n', encoding='utf-8')

        assert [use[2] for use in _external_uses(tmp_path)] == ['actions/checkout@v7']

    def it_runs_the_test_job_when_any_workflow_changes(self) -> None:
        ci = yaml.safe_load((WORKFLOWS_DIR / 'ci.yml').read_text(encoding='utf-8'))
        filters = yaml.safe_load(ci['jobs']['changes']['steps'][1]['with']['filters'])

        assert '.github/workflows/**' in filters['src']
