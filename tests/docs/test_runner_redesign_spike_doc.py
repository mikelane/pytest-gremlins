"""Drift check: the runner redesign spike report meets the acceptance criteria of issue #538."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs' / 'performance' / 'runner-redesign-spike.md'
FOLLOW_UP_ISSUES = ('#802', '#803', '#804')


@pytest.mark.medium
class DescribeRunnerRedesignSpikeReport:
    def it_disables_the_plugin_with_the_name_its_entry_point_registers(self) -> None:
        pyproject = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        entry_point_names = set(pyproject['project']['entry-points']['pytest11'])
        text = DOC.read_text()

        assert entry_point_names == {'gremlins'}
        assert '-p no:pytest_gremlins' not in text
        assert '-p no:gremlins' in text

    def it_records_a_prototype_result_for_design_1(self) -> None:
        text = DOC.read_text()

        assert 'is **not prototyped**' not in text
        assert re.search(r'^## Design 1 prototype results$', text, re.MULTILINE) is not None

    @pytest.mark.parametrize('issue', FOLLOW_UP_ISSUES)
    def it_links_each_filed_follow_up_issue(self, issue: str) -> None:
        assert issue in DOC.read_text()

    def it_addresses_one_subprocess_per_batch(self) -> None:
        assert 'one subprocess per batch' in DOC.read_text().lower()

    def it_profiles_phases_beyond_interpreter_start_and_import(self) -> None:
        text = DOC.read_text()

        assert 'collect-only' in text
        assert 'Load average' in text

    def it_gives_one_recommendation_without_hedging_between_designs(self) -> None:
        text = DOC.read_text()

        assert 'not yet safe enough' not in text
        assert len(re.findall(r'^Recommendation:', text, re.MULTILINE)) == 1
