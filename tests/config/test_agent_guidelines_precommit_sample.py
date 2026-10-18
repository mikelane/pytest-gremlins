"""The sample pre-commit config in AGENT_GUIDELINES.md mirrors the repo's real .pre-commit-config.yaml."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDELINES_PATH = REPO_ROOT / 'docs' / 'design' / 'AGENT_GUIDELINES.md'
PRECOMMIT_CONFIG_PATH = REPO_ROOT / '.pre-commit-config.yaml'
SAMPLE_PATTERN = re.compile(r'### Pre-commit\n.*?```yaml\n(?P<sample>.*?)\n```', re.DOTALL)


def _load_sample_repos() -> list[dict[str, Any]]:
    match = SAMPLE_PATTERN.search(GUIDELINES_PATH.read_text(encoding='utf-8'))
    assert match is not None, 'AGENT_GUIDELINES.md has no "### Pre-commit" yaml sample'
    return yaml.safe_load(match.group('sample'))['repos']


def _load_real_repos() -> list[dict[str, Any]]:
    return yaml.safe_load(PRECOMMIT_CONFIG_PATH.read_text(encoding='utf-8'))['repos']


def _remote_revs(repos: list[dict[str, Any]]) -> dict[str, str]:
    return {repo['repo']: repo['rev'] for repo in repos if repo['repo'] != 'local'}


def _local_hook_entries(repos: list[dict[str, Any]]) -> dict[str, str]:
    return {hook['id']: hook['entry'] for repo in repos if repo['repo'] == 'local' for hook in repo['hooks']}


@pytest.mark.medium
class DescribeAgentGuidelinesPrecommitSample:
    @pytest.mark.parametrize('retired_repo', ['ruff-pre-commit', 'mirrors-mypy'])
    def it_omits_the_remote_repos_that_the_uv_local_hooks_replaced(self, retired_repo: str) -> None:
        sample_repo_urls = [repo['repo'] for repo in _load_sample_repos()]
        assert not any(retired_repo in url for url in sample_repo_urls)

    def it_pins_every_remote_repo_to_the_rev_in_the_real_config(self) -> None:
        real_revs = _remote_revs(_load_real_repos())
        sample_revs = _remote_revs(_load_sample_repos())
        assert sample_revs
        assert {url: real_revs.get(url) for url in sample_revs} == sample_revs

    def it_shows_local_hooks_with_the_entry_in_the_real_config(self) -> None:
        real_entries = _local_hook_entries(_load_real_repos())
        sample_entries = _local_hook_entries(_load_sample_repos())
        assert sample_entries
        assert {hook_id: real_entries.get(hook_id) for hook_id in sample_entries} == sample_entries
