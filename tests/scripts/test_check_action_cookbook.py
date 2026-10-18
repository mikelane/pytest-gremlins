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
    def it_reads_input_names_with_their_defaults(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML)

        assert action.inputs == {'parallel': 'true', 'workers': ''}

    def it_reads_output_names(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML)

        assert action.outputs == frozenset({'score', 'passed'})

    def it_treats_a_missing_default_as_the_empty_string_like_github_does(self, checker: ModuleType) -> None:
        text = "inputs:\n  token:\n    description: 'x'\n    required: true\noutputs: {}\n"

        assert checker.parse_action(text).inputs == {'token': ''}

    def it_renders_a_yaml_boolean_default_as_the_lowercase_string_actions_use(self, checker: ModuleType) -> None:
        text = 'inputs:\n  flag:\n    default: true\noutputs: {}\n'

        assert checker.parse_action(text).inputs == {'flag': 'true'}

    def it_treats_an_action_without_outputs_as_having_none(self, checker: ModuleType) -> None:
        assert checker.parse_action('inputs:\n  a:\n    default: x\n').outputs == frozenset()

    def it_rejects_text_that_is_not_yaml(self, checker: ModuleType) -> None:
        with pytest.raises(checker.ParseError, match='not valid YAML'):
            checker.parse_action('inputs: [unclosed')

    def it_rejects_a_document_that_is_not_a_mapping(self, checker: ModuleType) -> None:
        with pytest.raises(checker.ParseError, match='mapping'):
            checker.parse_action('- just\n- a list\n')

    @pytest.mark.parametrize('inputs', ['5', 'text', '[a, b]'])
    def it_rejects_inputs_that_are_not_a_mapping(self, checker: ModuleType, inputs: str) -> None:
        with pytest.raises(checker.ParseError, match='inputs'):
            checker.parse_action(f'inputs: {inputs}\n')

    @pytest.mark.parametrize('outputs', ['5', 'text', '[a, b]'])
    def it_rejects_outputs_that_are_not_a_mapping(self, checker: ModuleType, outputs: str) -> None:
        with pytest.raises(checker.ParseError, match='outputs'):
            checker.parse_action(f'inputs:\n  a:\n    default: x\noutputs: {outputs}\n')

    def it_rejects_an_input_whose_value_is_a_scalar(self, checker: ModuleType) -> None:
        with pytest.raises(checker.ParseError, match='parallel'):
            checker.parse_action('inputs:\n  parallel: yes-please\n')

    def it_accepts_an_input_declared_with_an_empty_value(self, checker: ModuleType) -> None:
        assert checker.parse_action('inputs:\n  parallel:\n').inputs == {'parallel': ''}

    def it_rejects_an_action_with_no_inputs_section(self, checker: ModuleType) -> None:
        with pytest.raises(checker.ParseError, match='no inputs'):
            checker.parse_action('name: demo\noutputs: {}\n')


@pytest.mark.small
class DescribeParseCookbook:
    def it_reads_input_names_with_unquoted_defaults(self, checker: ModuleType) -> None:
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert cookbook.inputs == {'parallel': 'true', 'workers': ''}

    def it_reads_output_names(self, checker: ModuleType) -> None:
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert cookbook.outputs == frozenset({'score', 'passed'})

    def it_stops_the_inputs_table_at_the_next_heading(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('## Action Outputs', '## Other\n\n| `stray` | `x` | y |\n\n## Action Outputs')

        assert 'stray' not in checker.parse_cookbook(text).inputs

    def it_keeps_a_default_that_contains_a_pipe_character(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace("| `workers` | `''` |", "| `workers` | `'a\\|b'` |")

        assert checker.parse_cookbook(text).inputs['workers'] == 'a|b'

    def it_rejects_a_cookbook_without_the_inputs_heading(self, checker: ModuleType) -> None:
        with pytest.raises(checker.ParseError, match='Action Inputs'):
            checker.parse_cookbook('# GitHub Action\n\n## Action Outputs\n\n| Output | Description |\n|---|---|\n')

    def it_rejects_a_cookbook_without_the_outputs_heading(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.split('## Action Outputs', maxsplit=1)[0]

        with pytest.raises(checker.ParseError, match='Action Outputs'):
            checker.parse_cookbook(text)

    def it_rejects_an_inputs_section_that_has_no_table_rows(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace("| `parallel` | `'true'` | Adds `--gremlin-parallel`. |\n", '').replace(
            "| `workers` | `''` | Worker count. |\n", ''
        )

        with pytest.raises(checker.ParseError, match='no rows'):
            checker.parse_cookbook(text)

    def it_rejects_an_inputs_table_whose_columns_are_not_input_and_default(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('| Input | Default | Description |', '| Name | Value | Description |')

        with pytest.raises(checker.ParseError, match='columns'):
            checker.parse_cookbook(text)

    def it_rejects_a_default_that_is_not_in_code_formatting(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace("| `parallel` | `'true'` |", '| `parallel` | true |')

        with pytest.raises(checker.ParseError, match='parallel'):
            checker.parse_cookbook(text)

    def it_reads_an_input_whose_default_is_an_empty_quoted_string_as_empty(self, checker: ModuleType) -> None:
        assert checker.parse_cookbook(COOKBOOK_MD).inputs['workers'] == ''

    def it_rejects_an_inputs_row_with_only_a_name_cell(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace("| `parallel` | `'true'` | Adds `--gremlin-parallel`. |", '| `parallel` |')

        with pytest.raises(checker.ParseError, match='parallel'):
            checker.parse_cookbook(text)

    def it_rejects_an_input_documented_twice(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace("| `workers` | `''` | Worker count. |", "| `parallel` | `'false'` | Again. |")

        with pytest.raises(checker.ParseError, match='twice'):
            checker.parse_cookbook(text)

    def it_does_not_end_the_section_at_a_third_level_heading(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('| `workers` |', '### Notes\n\n| `workers` |')

        assert 'workers' in checker.parse_cookbook(text).inputs

    def it_does_not_end_the_section_at_a_hash_line_inside_a_code_fence(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('| `workers` |', '```bash\n# a comment\n```\n\n| `workers` |')

        assert 'workers' in checker.parse_cookbook(text).inputs

    def it_reads_a_code_span_up_to_its_first_closing_backtick(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('| `score` | Mutation score |', '| `score` | see `x` and `y` |')

        assert checker.parse_cookbook(text).outputs == frozenset({'score', 'passed'})

    def it_rejects_a_cell_with_text_around_two_code_spans(self, checker: ModuleType) -> None:
        text = COOKBOOK_MD.replace('| `score` |', '| `a` and `b` |')

        with pytest.raises(checker.ParseError, match='code formatting'):
            checker.parse_cookbook(text)


@pytest.mark.small
class DescribeCompare:
    def it_reports_no_drift_when_both_sides_match(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML)
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert checker.compare(action, cookbook) == []

    def it_reports_an_input_the_cookbook_documents_but_the_action_lacks(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML.replace('  workers:', '  other:'))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert 'input `workers` is in the cookbook but not in action.yml' in checker.compare(action, cookbook)

    def it_reports_an_input_the_action_has_but_the_cookbook_omits(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML.replace('  workers:', '  other:'))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert 'input `other` is in action.yml but not in the cookbook' in checker.compare(action, cookbook)

    def it_reports_a_default_that_differs(self, checker: ModuleType) -> None:
        action = checker.parse_action(ACTION_YML.replace("default: 'true'", "default: 'false'"))
        cookbook = checker.parse_cookbook(COOKBOOK_MD)

        assert "input `parallel` default: action.yml has 'false', cookbook has 'true'" in checker.compare(
            action, cookbook
        )

    def it_reports_an_output_missing_from_either_side(self, checker: ModuleType) -> None:
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

    def it_exits_zero_when_they_match(self, tmp_path: Path) -> None:
        assert self._run(tmp_path, ACTION_YML, COOKBOOK_MD).returncode == 0

    def it_exits_one_on_drift(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ACTION_YML.replace("default: 'true'", "default: 'false'"), COOKBOOK_MD)

        assert result.returncode == 1

    def it_prints_the_drift_on_stdout(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ACTION_YML.replace("default: 'true'", "default: 'false'"), COOKBOOK_MD)

        assert "input `parallel` default: action.yml has 'false', cookbook has 'true'" in result.stdout

    def it_exits_two_when_the_cookbook_cannot_be_parsed(self, tmp_path: Path) -> None:
        assert self._run(tmp_path, ACTION_YML, '# nothing here\n').returncode == 2

    def it_names_the_parse_problem_on_stderr(self, tmp_path: Path) -> None:
        assert 'Action Inputs' in self._run(tmp_path, ACTION_YML, '# nothing here\n').stderr

    def it_marks_each_drift_line_with_a_sentinel_prefix(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ACTION_YML.replace("default: 'true'", "default: 'false'"), COOKBOOK_MD)

        assert "DRIFT: input `parallel` default: action.yml has 'false', cookbook has 'true'" in result.stdout

    def it_exits_two_when_an_inputs_row_has_no_default_cell(self, tmp_path: Path) -> None:
        cookbook = COOKBOOK_MD.replace("| `parallel` | `'true'` | Adds `--gremlin-parallel`. |", '| `parallel` |')

        assert self._run(tmp_path, ACTION_YML, cookbook).returncode == 2

    def it_exits_two_when_an_action_input_is_a_scalar(self, tmp_path: Path) -> None:
        action = 'inputs:\n  parallel: yes-please\noutputs:\n  score:\n    value: x\n'

        assert self._run(tmp_path, action, COOKBOOK_MD).returncode == 2

    @pytest.mark.parametrize('section', ['inputs: 5\noutputs: {}\n', 'inputs: text\noutputs: {}\n'])
    def it_exits_two_when_inputs_is_not_a_mapping(self, tmp_path: Path, section: str) -> None:
        assert self._run(tmp_path, section, COOKBOOK_MD).returncode == 2

    def it_accepts_an_empty_documented_default_for_an_input_with_no_default(self, tmp_path: Path) -> None:
        action = ACTION_YML.replace("    default: ''\n", '')

        assert self._run(tmp_path, action, COOKBOOK_MD).returncode == 0

    def it_exits_two_when_a_file_is_missing(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tmp_path / 'nope.yml'), str(tmp_path / 'nope.md')],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2


@pytest.mark.medium
class DescribeMain:
    def it_maps_an_unexpected_exception_to_exit_two_with_the_message_on_stderr(
        self,
        checker: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / 'action.yml').write_text(ACTION_YML)
        (tmp_path / 'github-action.md').write_text(COOKBOOK_MD)

        def explode(*_args: object) -> list[str]:
            raise RuntimeError('boom')

        monkeypatch.setattr(checker, 'compare', explode)

        status = checker.main([str(tmp_path / 'action.yml'), str(tmp_path / 'github-action.md')])

        assert (status, 'boom' in capsys.readouterr().err) == (2, True)
