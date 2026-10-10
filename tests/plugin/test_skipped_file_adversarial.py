"""Adversarial QA probes for skipped-file reporting (issue #638)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _describe_exception

AGE_SOURCE = 'def is_adult(age):\n    return age >= 18\n'
AGE_TEST = 'from demo.age import is_adult\n\n\ndef test_is_adult():\n    assert is_adult(20)\n'
PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["src"]\n'


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError('str() is broken')


def _write_project(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(PYPROJECT)
    pytester.mkdir('src')
    pytester.mkdir('src/demo')
    pytester.path.joinpath('src', 'demo', '__init__.py').write_text('')
    pytester.path.joinpath('src', 'demo', 'age.py').write_text(AGE_SOURCE)
    pytester.mkdir('tests')
    pytester.path.joinpath('tests', 'test_age.py').write_text(AGE_TEST)


@pytest.mark.small
class DescribeUnprintableException:
    def it_describes_an_exception_whose_str_raises(self) -> None:
        assert _describe_exception(UnprintableError()).startswith('UnprintableError')


@pytest.mark.medium
class DescribeSkipNoticeSurvivesExplain:
    def it_names_the_skipped_file_when_gremlin_explain_is_given(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise ValueError('boom')

        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', explode)
        _write_project(pytester)

        result = pytester.runpytest_inprocess(
            '--gremlins', '--gremlin-targets', 'src/demo', '--gremlin-explain', 'g001', '-p', 'no:test_categories'
        )

        result.stdout.fnmatch_lines(['*skipped *age.py*could not instrument (ValueError: boom)*'])
