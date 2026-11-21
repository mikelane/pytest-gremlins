"""Tests for scripts/check_no_wip_tests.py -- the release gate that refuses to ship unfinished (``wip``) scenarios."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_no_wip_tests.py'

WIP_TEST = """
import pytest

@pytest.mark.wip
def test_unfinished_feature():
    assert False
"""
FINISHED_TEST = """
def test_finished_feature():
    assert True
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_no_wip_tests', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _run_script(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--repo', str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeCheckNoWipTests:
    def it_exits_zero_when_no_test_is_marked_wip(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_finished.py', FINISHED_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == 'No wip tests found\n'

    def it_exits_zero_when_there_are_no_tests_at_all(self, tmp_path: Path) -> None:
        result = _run_script(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr

    def it_exits_one_and_lists_the_wip_test_id(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_unfinished.py', WIP_TEST)
        _write(tmp_path, 'tests/test_finished.py', FINISHED_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'tests/test_unfinished.py::test_unfinished_feature' in result.stdout
        assert 'test_finished_feature' not in result.stdout

    def it_lists_every_wip_test(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_one.py', WIP_TEST)
        _write(tmp_path, 'tests/test_two.py', WIP_TEST)

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'tests/test_one.py::test_unfinished_feature' in result.stdout
        assert 'tests/test_two.py::test_unfinished_feature' in result.stdout

    def it_exits_two_when_collection_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_broken.py', 'def test_broken(:\n')

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert 'while collecting wip tests' in result.stderr


@pytest.mark.small
class DescribeParseCollectedIds:
    def it_keeps_only_test_id_lines(self) -> None:
        script = _load_script()
        output = 'tests/a.py::test_x\ntests/b.py::DescribeY::it_z\n\n2/9 tests collected (7 deselected) in 0.01s\n'

        assert script.parse_collected_ids(output) == ['tests/a.py::test_x', 'tests/b.py::DescribeY::it_z']

    def it_ignores_a_warning_line_that_quotes_a_test_id(self) -> None:
        script = _load_script()
        output = '/venv/plugin.py:171: PytestWarning: Test has no size marker: tests/a.py::test_x\ntests/a.py::test_y\n'

        assert script.parse_collected_ids(output) == ['tests/a.py::test_y']


def _feature(*lines: str) -> str:
    return '\n'.join(lines) + '\n'


@pytest.mark.medium
class DescribeFeatureFileScan:
    """``@wip`` in a ``.feature`` file is found by parsing it with the official Gherkin parser."""

    @pytest.mark.parametrize(
        ('content', 'line'),
        [
            (_feature('@wip', 'Feature: Unfinished', '', '  Scenario: S', '    Given a thing'), 1),
            (_feature('Feature: F', '', '  @wip', '  Scenario: S', '    Given a thing'), 3),
            (_feature('Feature: F', '', '  @smoke @wip', '  Scenario: S', '    Given a thing'), 3),
            (_feature('Feature: F', '', '  @wip @smoke', '  Scenario Outline: S', '    Given <x>'), 3),
            (_feature('Feature: F', '', '  @wip', '  Rule: R', '    Scenario: S', '      Given a thing'), 3),
            (_feature('Feature: F', '', '  Rule: R', '    @wip', '    Scenario: S', '      Given a thing'), 4),
            (
                _feature(
                    'Feature: F',
                    '',
                    '  Scenario Outline: S',
                    '    Given <x>',
                    '',
                    '    @wip',
                    '    Examples:',
                    '      | x |',
                ),
                6,
            ),
            (_feature('Feature: F', '', '  @a', '  @wip', '  Scenario: S', '    Given a thing'), 4),
            (_feature('Feature: F', '', '  @wip # not done', '  Scenario: S', '    Given a thing'), 3),
            (_feature('Feature: F', '', '  @smoke@wip', '  Scenario: S', '    Given a thing'), 3),
            (_feature('@wip', 'Business Need: F', '  Scenario: s', '    Given x'), 1),
        ],
        ids=[
            'feature',
            'scenario',
            'scenario-second-tag',
            'scenario-outline-first-tag',
            'rule-follows-tag',
            'scenario-inside-rule',
            'examples',
            'second-tag-line',
            'trailing-comment',
            'packed-against-another-tag',
            'keyword-synonym',
        ],
    )
    def it_finds_a_wip_tag_wherever_gherkin_attaches_it(self, tmp_path: Path, content: str, line: int) -> None:
        _write(tmp_path, 'features/unfinished.feature', content)

        hits = _load_script().find_wip_feature_tags(tmp_path)

        assert hits == [f'features/unfinished.feature:{line}']

    @pytest.mark.parametrize('tag_line', ['@wip @', '@wip@', '@@wip', '@ wip', '@smoke @ @wip'])
    def it_finds_a_wip_tag_on_a_line_with_a_stray_at_sign(self, tmp_path: Path, tag_line: str) -> None:
        _write(
            tmp_path,
            'features/stray.feature',
            _feature('Feature: F', '', f'  {tag_line}', '  Scenario: S', '    Given a'),
        )

        assert _load_script().find_wip_feature_tags(tmp_path) == ['features/stray.feature:3']

    @pytest.mark.parametrize('tag_line', ['@wip later', '@smoke wip'])
    def it_cannot_check_a_tag_line_whose_tag_contains_whitespace(self, tmp_path: Path, tag_line: str) -> None:
        _write(
            tmp_path,
            'features/bad.feature',
            _feature('Feature: F', '', f'  {tag_line}', '  Scenario: S', '    Given a'),
        )

        script = _load_script()

        with pytest.raises(script.CannotCheckError, match=r'bad\.feature'):
            script.find_wip_feature_tags(tmp_path)

    @pytest.mark.parametrize(
        'content',
        [
            _feature('Feature: F', '', '  # @wip', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '', '  @wipe', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '', '  @wip-later', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '', '  @wip2 @not_wip', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '', '  Scenario: S', '    Given an email a@wip.example'),
            _feature('Feature: F', '', '  Scenario: S', '    Given the tag @wip is mentioned in a step'),
            _feature('Feature: This feature talks about @wip', '', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '  A description that mentions @wip in prose', '', '  Scenario: S'),
            _feature('Feature: F', '  Scenario: S', '    Given a source', '      """', '      @wip', '      """'),
            _feature('Feature: F', '', '  @smoke', '  Scenario: S', '    Given a thing'),
            _feature('Feature: F', '', '  @wip,', '  Scenario: S', '    Given a thing'),
        ],
        ids=[
            'commented-out',
            'longer-tag',
            'hyphenated-tag',
            'tags-containing-wip',
            'email-in-step',
            'tag-text-in-step',
            'tag-text-in-title',
            'tag-text-in-description',
            'tag-text-in-docstring',
            'other-tag',
            'wip-with-trailing-comma',
        ],
    )
    def it_ignores_comments_look_alikes_and_text_that_is_not_a_tag(self, tmp_path: Path, content: str) -> None:
        _write(tmp_path, 'features/finished.feature', content)

        assert _load_script().find_wip_feature_tags(tmp_path) == []

    def it_scans_feature_files_in_nested_directories(self, tmp_path: Path) -> None:
        _write(tmp_path, 'features/deep/er/unfinished.feature', _feature('@wip', 'Feature: F'))

        assert _load_script().find_wip_feature_tags(tmp_path) == ['features/deep/er/unfinished.feature:1']

    def it_reports_every_hit_in_every_file_in_a_stable_order(self, tmp_path: Path) -> None:
        _write(tmp_path, 'features/b.feature', _feature('@wip', 'Feature: B'))
        _write(
            tmp_path,
            'features/a.feature',
            _feature('Feature: A', '@wip', 'Scenario: S', 'Given x', '@wip', 'Scenario: T'),
        )

        assert _load_script().find_wip_feature_tags(tmp_path) == [
            'features/a.feature:2',
            'features/a.feature:5',
            'features/b.feature:1',
        ]

    def it_finds_nothing_without_a_features_directory(self, tmp_path: Path) -> None:
        assert _load_script().find_wip_feature_tags(tmp_path) == []

    def it_finds_nothing_in_an_empty_feature_file(self, tmp_path: Path) -> None:
        _write(tmp_path, 'features/empty.feature', '')

        assert _load_script().find_wip_feature_tags(tmp_path) == []

    def it_fails_the_script_with_exit_one_naming_file_and_line(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_finished.py', FINISHED_TEST)
        _write(tmp_path, 'features/unfinished.feature', _feature('Feature: F', '', '  @wip', '  Scenario: S'))

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'features/unfinished.feature:3' in result.stdout

    def it_lists_collected_tests_and_feature_tags_together(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_unfinished.py', WIP_TEST)
        _write(tmp_path, 'features/unfinished.feature', _feature('@wip', 'Feature: F'))

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'tests/test_unfinished.py::test_unfinished_feature' in result.stdout
        assert 'features/unfinished.feature:1' in result.stdout

    def it_still_fails_on_a_feature_tag_when_collection_is_broken(self, tmp_path: Path) -> None:
        _write(tmp_path, 'tests/test_broken.py', 'def test_broken(:\n')
        _write(tmp_path, 'features/unfinished.feature', _feature('@wip', 'Feature: F'))

        result = _run_script(tmp_path)

        assert result.returncode == 1
        assert 'features/unfinished.feature:1' in result.stdout

    def it_exits_two_when_a_feature_file_cannot_be_decoded(self, tmp_path: Path) -> None:
        path = tmp_path / 'features' / 'bad.feature'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\xff\xfe\x00bad')

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert 'cannot read features/bad.feature' in result.stderr

    def it_exits_two_when_a_feature_path_cannot_be_read(self, tmp_path: Path) -> None:
        (tmp_path / 'features' / 'directory.feature').mkdir(parents=True)

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert 'cannot read features/directory.feature' in result.stderr

    def it_exits_two_when_a_feature_file_is_malformed(self, tmp_path: Path) -> None:
        _write(tmp_path, 'features/malformed.feature', 'this is not gherkin\n')

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert 'cannot parse features/malformed.feature' in result.stderr

    def it_exits_two_for_a_malformed_file_even_when_another_file_holds_a_wip_tag(self, tmp_path: Path) -> None:
        _write(tmp_path, 'features/a_unfinished.feature', _feature('@wip', 'Feature: F'))
        _write(tmp_path, 'features/b_malformed.feature', 'this is not gherkin\n')

        result = _run_script(tmp_path)

        assert result.returncode == 2
        assert 'b_malformed.feature' in result.stderr

    def it_finds_a_wip_tag_in_a_feature_file_that_starts_with_a_byte_order_mark(self, tmp_path: Path) -> None:
        path = tmp_path / 'features' / 'bom.feature'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\xef\xbb\xbf@wip\nFeature: F\n')

        assert _load_script().find_wip_feature_tags(tmp_path) == ['features/bom.feature:1']


@pytest.mark.small
class DescribeAnnotationEscaping:
    """The ``::error`` annotation must escape ``%``, CR and LF or GitHub Actions misreads the message."""

    @pytest.mark.parametrize(
        ('test_id', 'escaped'),
        [
            ('t.py::test[50%]', 't.py::test[50%25]'),
            ('t.py::test[a\rb]', 't.py::test[a%0Db]'),
            ('t.py::test[a\nb]', 't.py::test[a%0Ab]'),
        ],
    )
    def it_escapes_special_characters_in_the_annotation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], test_id: str, escaped: str
    ) -> None:
        monkeypatch.setenv('GITHUB_ACTIONS', 'true')

        _load_script()._report_failure([test_id])

        annotation = capsys.readouterr().out.splitlines()[0]
        assert annotation == (
            '::error title=Release contains wip tests::1 wip test(s) or tag(s) found; '
            f'a release must not ship an unfinished feature:%0A  {escaped}'
        )

    def it_prints_no_annotation_outside_github_actions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv('GITHUB_ACTIONS', raising=False)

        _load_script()._report_failure(['t.py::a', 't.py::b'])

        assert capsys.readouterr().out == (
            '2 wip test(s) or tag(s) found; a release must not ship an unfinished feature:\n  t.py::a\n  t.py::b\n'
        )


QUIET_ADDOPTS_CONFIG = """[pytest]
markers = wip: unfinished
addopts = -q
"""


@pytest.mark.medium
class DescribeCollectionOutputFormat:
    """Extra ``-q`` from addopts or PYTEST_ADDOPTS makes ``--collect-only`` print ``file: N``, which has no IDs."""

    def it_finds_a_wip_test_when_the_project_adds_q_to_addopts(self, tmp_path: Path) -> None:
        _write(tmp_path, 'pytest.ini', QUIET_ADDOPTS_CONFIG)
        _write(tmp_path, 'tests/test_a.py', WIP_TEST)

        assert _load_script().find_wip_tests(tmp_path) == ['tests/test_a.py::test_unfinished_feature']

    def it_finds_a_wip_test_when_pytest_addopts_adds_q(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-q')
        _write(tmp_path, 'tests/test_a.py', WIP_TEST)

        assert _load_script().find_wip_tests(tmp_path) == ['tests/test_a.py::test_unfinished_feature']

    def it_raises_when_pytest_collected_items_but_no_ids_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        script = _load_script()
        answer = subprocess.CompletedProcess(args=[], returncode=0, stdout='tests/test_a.py: 1\n', stderr='')
        monkeypatch.setattr(script.subprocess, 'run', lambda *_args, **_kwargs: answer)

        with pytest.raises(script.CannotCheckError, match='no test IDs'):
            script.find_wip_tests(Path())
