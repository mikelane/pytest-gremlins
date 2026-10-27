"""Every non-local ``uses:`` in a workflow pins a full commit SHA, with the release tag in a trailing comment.

A moved or compromised tag would otherwise run new code with the job's token and secrets.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
DEPENDABOT_PATH = REPO_ROOT / '.github' / 'dependabot.yml'

USES_LINE = re.compile(r'^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$')
PINNED_REF = re.compile(r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$')
TAG_COMMENT = re.compile(r'^\s+#\s*v?\d[\w.+-]*\s*$')


def _external_uses() -> list[tuple[str, int, str, str]]:
    found = []
    for workflow in sorted(WORKFLOWS_DIR.glob('*.yml')):
        for number, line in enumerate(workflow.read_text(encoding='utf-8').splitlines(), start=1):
            match = USES_LINE.match(line)
            if match and not match['ref'].startswith('./'):
                found.append((workflow.name, number, match['ref'], match['rest']))
    return found


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
        assert 'package-ecosystem: github-actions' in DEPENDABOT_PATH.read_text(encoding='utf-8')
