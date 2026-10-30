"""Drift check: the runner redesign spike report meets the acceptance criteria of issue #538."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs' / 'performance' / 'runner-redesign-spike.md'
FOLLOW_UP_ISSUES = ('#802', '#803', '#804')
BOOTSTRAP_ONLY_TEST_IDS = (
    'it_zaps_every_mutant_whatever_the_test_style[parallel]',
    'it_zaps_every_mutant_whatever_the_test_style[batch]',
)
FIDELITY_TEST_IDS = (
    'it_zaps_every_mutant_whatever_the_test_style[default]',
    'it_zaps_every_mutant_whatever_the_test_style[parallel]',
    'it_zaps_every_mutant_whatever_the_test_style[batch]',
    'it_runs_every_style_of_test_body_against_a_mutant',
    'it_leaves_every_mutant_survived[fixture]',
    'it_leaves_every_mutant_survived[parametrized]',
    'it_still_zaps_with_a_fixture_taking_test_that_covers_the_target',
    'it_does_not_count_a_hook_dependent_test_as_a_kill',
    'it_does_not_count_a_conftest_dependent_test_as_a_kill[module_level]',
    'it_does_not_count_a_conftest_dependent_test_as_a_kill[pytest_configure]',
    'it_does_not_count_a_failed_lazy_helper_import_as_a_kill',
    'it_zaps_with_a_test_that_imports_a_sibling_helper',
    'it_zaps_with_a_test_whose_helper_is_on_the_pytest_ini_pythonpath',
)


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

    def it_links_the_design_1_prototype_branch(self) -> None:
        assert 'issue-538-design1-prototype' in DOC.read_text()

    def it_does_not_label_pytest_version_as_plugin_load(self) -> None:
        assert '(plugin load, no collection)' not in DOC.read_text()

    def it_does_not_claim_the_inflated_plugin_cost_from_a_busy_machine(self) -> None:
        text = DOC.read_text()

        assert 'about 230ms' not in text
        assert '1052' not in text

    @pytest.mark.parametrize('test_id', FIDELITY_TEST_IDS)
    def it_records_a_per_test_result_for_each_fidelity_case(self, test_id: str) -> None:
        rows = [line for line in DOC.read_text().splitlines() if test_id in line]

        assert len(rows) == 1
        assert '| pass' in rows[0]

    @pytest.mark.parametrize('test_id', BOOTSTRAP_ONLY_TEST_IDS)
    def it_marks_the_fidelity_cases_that_never_reach_the_prototype(self, test_id: str) -> None:
        row = next(line for line in DOC.read_text().splitlines() if test_id in line)

        assert '| pass (bootstrap, not the prototype) |' in row

    def it_does_not_claim_all_thirteen_cases_ran_through_the_prototype(self) -> None:
        text = ' '.join(DOC.read_text().split())

        assert '13 of 13 pass' not in text
        assert '11 of the 13 cases' in text

    def it_says_the_suites_cannot_tell_whether_a_reused_worker_switches_gremlin(self) -> None:
        assert 'cannot tell whether a reused worker switches to the new gremlin' in ' '.join(DOC.read_text().split())

    def it_does_not_claim_the_fidelity_suites_were_skipped(self) -> None:
        assert 'were not run against the prototype' not in DOC.read_text()

    def it_says_what_the_fidelity_suites_do_not_cover(self) -> None:
        assert 'do not cover cross-gremlin state leakage' in ' '.join(DOC.read_text().split())

    def it_changes_the_toggle_each_round_in_the_prototype_case(self) -> None:
        assert 'changes the active-gremlin toggle each round' in ' '.join(DOC.read_text().split())

    def it_gives_measured_per_round_costs_not_a_range_for_all_later_rounds(self) -> None:
        text = DOC.read_text()

        assert 'Per-round cost after the first: 2 to 4ms' not in text
        assert 'Round 2' in text
        assert 'Round 3 and later' in text

    def it_lists_the_maintainer_decisions_as_open_questions(self) -> None:
        text = DOC.read_text()

        assert re.search(r'^## Open questions for the maintainer$', text, re.MULTILINE) is not None
        assert 'fork-after-collect' in text
        assert 'disables plugin autoload' in text

    def it_gives_one_recommendation_without_hedging_between_designs(self) -> None:
        text = DOC.read_text()

        assert 'not yet safe enough' not in text
        assert len(re.findall(r'^Recommendation:', text, re.MULTILINE)) == 1
