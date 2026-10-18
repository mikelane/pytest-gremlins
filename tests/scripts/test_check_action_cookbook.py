"""Tests for scripts/check_action_cookbook.py -- the weekly check that the cookbook matches the action's action.yml."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_action_cookbook.py'

ACTION_YML = """\
name: 'demo'
inputs:
  parallel:
    description: 'Enable parallel execution'
    required: false
    default: 'true'
  workers:
    description: 'Worker count'
    required: false
    default: ''
outputs:
  score:
    description: 'Mutation score'
    value: ${{ steps.parse.outputs.score }}
  passed:
    description: 'Whether it passed'
    value: ${{ steps.ratchet.outputs.passed }}
runs:
  using: 'composite'
  steps: []
"""

COOKBOOK_MD = """\
# GitHub Action

## Action Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `parallel` | `'true'` | Adds `--gremlin-parallel`. |
| `workers` | `''` | Worker count. |

## Action Outputs

| Output | Description |
|--------|-------------|
| `score` | Mutation score |
| `passed` | `'true'` if the score is at or above the threshold |

## Basic Usage
"""


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_action_cookbook', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def checker() -> ModuleType:
    return _load_checker()


@pytest.mark.small
class DescribeParseAction:
    def it_reads_input_names_with_their_defaults(self, checker):
        action = checker.parse_action(ACTION_YML)

        assert action.inputs == {'parallel': 'true', 'workers': ''}

    def it_reads_output_names(self, checker):
        action = checker.parse_action(ACTION_YML)

        assert action.outputs == frozenset({'score', 'passed'})

    def it_reports_a_missing_default_as_none(self, checker):
        text = "inputs:\n  token:\n    description: 'x'\n    required: true\noutputs: {}\n"

        assert checker.parse_action(text).inputs == {'token': None}

    def it_renders_a_yaml_boolean_default_as_the_lowercase_string_actions_use(self, checker):
        text = 'inputs:\n  flag:\n    default: true\noutputs: {}\n'

        assert checker.parse_action(text).inputs == {'flag': 'true'}

    def it_treats_an_action_without_outputs_as_having_none(self, checker):
        assert checker.parse_action('inputs:\n  a:\n    default: x\n').outputs == frozenset()

    def it_rejects_text_that_is_not_yaml(self, checker):
        with pytest.raises(checker.ParseError, match='not valid YAML'):
            checker.parse_action('inputs: [unclosed')

    def it_rejects_a_document_that_is_not_a_mapping(self, checker):
        with pytest.raises(checker.ParseError, match='mapping'):
            checker.parse_action('- just\n- a list\n')

    def it_rejects_an_action_with_no_inputs_section(self, checker):
        with pytest.raises(checker.ParseError, match='no inputs'):
            checker.parse_action('name: demo\noutputs: {}\n')


@pytest.mark.small
class DescribeParseCookbook:
    def it_reads_input_names_with_unquoted_defaults(self, checker):
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert cookbook.inputs == {'parallel': 'true', 'workers': ''}

    def it_reads_output_names(self, checker):
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert cookbook.outputs == frozenset({'score', 'passed'})

    def it_stops_the_inputs_table_at_the_next_heading(self, checker):
        text = COOKBOOK_MD.replace('## Action Outputs', '## Other\n\n| `stray` | `x` | y |\n\n## Action Outputs')

        assert 'stray' not in checker.parse_cookbook(text).inputs

    def it_keeps_a_default_that_contains_a_pipe_character(self, checker):
        text = COOKBOOK_MD.replace("| `workers` | `''` |", "| `workers` | `'a\\|b'` |")

        assert checker.parse_cookbook(text).inputs['workers'] == 'a|b'

    def it_rejects_a_cookbook_without_the_inputs_heading(self, checker):
        with pytest.raises(checker.ParseError, match='Action Inputs'):
            checker.parse_cookbook('# GitHub Action\n\n## Action Outputs\n\n| Output | Description |\n|---|---|\n')

    def it_rejects_a_cookbook_without_the_outputs_heading(self, checker):
        text = COOKBOOK_MD.split('## Action Outputs', maxsplit=1)[0]

        with pytest.raises(checker.ParseError, match='Action Outputs'):
            checker.parse_cookbook(text)

    def it_rejects_an_inputs_section_that_has_no_table_rows(self, checker):
        text = COOKBOOK_MD.replace("| `parallel` | `'true'` | Adds `--gremlin-parallel`. |\n", '').replace(
            "| `workers` | `''` | Worker count. |\n", ''
        )

        with pytest.raises(checker.ParseError, match='no rows'):
            checker.parse_cookbook(text)

    def it_rejects_an_inputs_table_whose_columns_are_not_input_and_default(self, checker):
        text = COOKBOOK_MD.replace('| Input | Default | Description |', '| Name | Value | Description |')

        with pytest.raises(checker.ParseError, match='columns'):
            checker.parse_cookbook(text)

    def it_rejects_a_default_that_is_not_in_code_formatting(self, checker):
        text = COOKBOOK_MD.replace("| `parallel` | `'true'` |", '| `parallel` | true |')

        with pytest.raises(checker.ParseError, match='parallel'):
            checker.parse_cookbook(text)


@pytest.mark.small
class DescribeCompare:
    def it_reports_no_drift_when_both_sides_match(self, checker):
        action = checker.parse_action(ACTION_YML)
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert checker.compare(action, cookbook) == []

    def it_reports_an_input_the_cookbook_documents_but_the_action_lacks(self, checker):
        action = checker.parse_action(ACTION_YML.replace('  workers:', '  other:'))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert 'input `workers` is in the cookbook but not in action.yml' in checker.compare(action, cookbook)

    def it_reports_an_input_the_action_has_but_the_cookbook_omits(self, checker):
        action = checker.parse_action(ACTION_YML.replace('  workers:', '  other:'))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert 'input `other` is in action.yml but not in the cookbook' in checker.compare(action, cookbook)

    def it_reports_a_default_that_differs(self, checker):
        action = checker.parse_action(ACTION_YML.replace("default: 'true'", "default: 'false'"))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert "input `parallel` default: action.yml has 'false', cookbook has 'true'" in checker.compare(
            action, cookbook
        )

    def it_reports_an_output_missing_from_either_side(self, checker):
        action = checker.parse_action(ACTION_YML.replace('  passed:', '  fresh:'))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert checker.compare(action, cookbook) == [
            'output `fresh` is in action.yml but not in the cookbook',
            'output `passed` is in the cookbook but not in action.yml',
        ]


@pytest.mark.medium
class DescribeCommandLine:
    @staticmethod
    def _run(tmp_path: Path, action: str, cookbook: str) -> subprocess.CompletedProcess[str]:
        action_path = tmp_path / 'action.yml'
        cookbook_path = tmp_path / 'github-action.md'
        action_path.write_text(action)
        cookbook_path.write_text(cookbook)
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(action_path), str(cookbook_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def it_exits_zero_when_they_match(self, tmp_path):
        assert self._run(tmp_path, ACTION_YML, COOKBOOK_MD).returncode == 0

    def it_exits_one_on_drift(self, tmp_path):
        result = self._run(tmp_path, ACTION_YML.replace("default: 'true'", "default: 'false'"), COOKBOOK_MD)

        assert result.returncode == 1

    def it_prints_the_drift_on_stdout(self, tmp_path):
        result = self._run(tmp_path, ACTION_YML.replace("default: 'true'", "default: 'false'"), COOKBOOK_MD)

        assert "input `parallel` default: action.yml has 'false', cookbook has 'true'" in result.stdout

    def it_exits_two_when_the_cookbook_cannot_be_parsed(self, tmp_path):
        assert self._run(tmp_path, ACTION_YML, '# nothing here\n').returncode == 2

    def it_names_the_parse_problem_on_stderr(self, tmp_path):
        assert 'Action Inputs' in self._run(tmp_path, ACTION_YML, '# nothing here\n').stderr

    def it_exits_two_when_a_file_is_missing(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tmp_path / 'nope.yml'), str(tmp_path / 'nope.md')],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
