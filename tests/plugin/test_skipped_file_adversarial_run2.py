"""Adversarial QA run 2 probes for skipped-file reporting (issue #638)."""

from __future__ import annotations

import re

import pytest

from pytest_gremlins import plugin

_GREMLIN_PROGRESS_RE = re.compile(r'Gremlin \d+/\d+: (\S+)')

AGE_SOURCE = 'def is_adult(age):\n    return age >= 18\n'
BROKEN_SOURCE = 'def is_child(age):\n    return age < 18\n'
AGE_TEST = (
    'from demo.age import is_adult\n'
    'from demo.broken import is_child\n\n\n'
    'def test_is_adult():\n    assert is_adult(20)\n\n\n'
    'def test_is_child():\n    assert is_child(3)\n'
)
PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["src"]\n'
SKIP_LINE = '*skipped *broken.py*could not instrument (ValueError: boom)*'

_real_transform = plugin.transform_source


def _explode_on_broken(source: str, file_path: str, *args: object, **kwargs: object) -> object:
    if file_path.endswith('broken.py'):
        raise ValueError('boom')
    return _real_transform(source, file_path, *args, **kwargs)  # type: ignore[arg-type]


def _write_mixed_project(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(PYPROJECT)
    pytester.mkdir('src')
    pytester.mkdir('src/demo')
    pytester.path.joinpath('src', 'demo', '__init__.py').write_text('')
    pytester.path.joinpath('src', 'demo', 'age.py').write_text(AGE_SOURCE)
    pytester.path.joinpath('src', 'demo', 'broken.py').write_text(BROKEN_SOURCE)
    pytester.mkdir('tests')
    pytester.path.joinpath('tests', 'test_age.py').write_text(AGE_TEST)


def _skip_line_count(result: pytest.RunResult) -> int:
    return sum('could not instrument' in line for line in result.outlines)


@pytest.mark.medium
class DescribeMixedSkipWithExplain:
    def it_names_the_skipped_file_when_explaining_a_gremlin_from_the_other_file(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', _explode_on_broken)
        _write_mixed_project(pytester)
        bootstrap = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '-p', 'no:test_categories'
        )
        gremlin_id = _GREMLIN_PROGRESS_RE.search(bootstrap.stdout.str()).group(1)  # type: ignore[union-attr]

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '--gremlin-explain', gremlin_id, '-p', 'no:test_categories'
        )

        result.stdout.fnmatch_lines([SKIP_LINE, f'*--gremlin-explain: diagnostic for {gremlin_id}*'])

    def it_names_the_skipped_file_when_the_explained_id_does_not_exist(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', _explode_on_broken)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '--gremlin-explain', 'g999', '-p', 'no:test_categories'
        )

        result.stdout.fnmatch_lines([SKIP_LINE])

    def it_points_at_the_skipped_files_when_the_explained_id_does_not_exist(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', _explode_on_broken)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '--gremlin-explain', 'g999', '-p', 'no:test_categories'
        )

        result.stdout.fnmatch_lines(["*no gremlin with id 'g999'*Files were skipped (see above).*"])


@pytest.mark.medium
class DescribeSkipNoticePrintedOnce:
    def it_prints_the_notice_once_without_explain(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', _explode_on_broken)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess('--gremlins', '--gremlin-targets', 'src/demo', '-p', 'no:test_categories')

        assert _skip_line_count(result) == 1

    def it_prints_the_notice_once_when_every_file_is_skipped_under_explain(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise ValueError('boom')

        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', explode)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '--gremlin-explain', 'g001', '-p', 'no:test_categories'
        )

        assert _skip_line_count(result) == 3

    def it_prints_the_notice_once_under_xdist(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', _explode_on_broken)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '-n', '2', '-p', 'no:test_categories'
        )

        assert _skip_line_count(result) == 1

    def it_prints_the_notice_under_xdist_with_explain_when_every_file_is_skipped(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise ValueError('boom')

        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', explode)
        _write_mixed_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins',
            '--gremlin-targets',
            'src/demo',
            '--gremlin-explain',
            'g001',
            '-n',
            '2',
            '-p',
            'no:test_categories',
        )

        assert _skip_line_count(result) == 3
