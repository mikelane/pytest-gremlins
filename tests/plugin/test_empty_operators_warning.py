"""The empty-operators warning and the non-table ``[tool]`` error, end to end (issue #796)."""

from __future__ import annotations

import pytest

_NO_CATEGORIES = ('-p', 'no:test_categories')
_EMPTY_OPERATORS_WARNING = '[tool.pytest-gremlins].operators is empty'
_TARGET = 'def add(a, b):\n    return a + b\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
_EMPTY_OPERATORS = '[tool.pytest-gremlins]\noperators = []\n'


def _output(result: pytest.RunResult) -> str:
    return result.stdout.str() + result.stderr.str()


@pytest.mark.medium
def it_does_not_warn_about_empty_operators_when_the_cli_names_operators(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(_EMPTY_OPERATORS)
    pytester.makepyfile(target=_TARGET, test_target=_TEST)

    result = pytester.runpytest_subprocess(
        '--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', *_NO_CATEGORIES
    )

    assert _EMPTY_OPERATORS_WARNING not in _output(result), _output(result)


@pytest.mark.medium
def it_warns_about_empty_operators_when_the_cli_names_none(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(_EMPTY_OPERATORS)
    pytester.makepyfile(target=_TARGET, test_target=_TEST)

    result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py', *_NO_CATEGORIES)

    assert _EMPTY_OPERATORS_WARNING in _output(result), _output(result)


@pytest.mark.medium
def it_stops_with_exit_code_4_for_a_non_table_tool_entry_when_pytest_reads_another_config_file(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyprojecttoml('tool = 5\n')
    pytester.makefile('.ini', other='[pytest]\n')
    pytester.makepyfile(target=_TARGET, test_target=_TEST)

    result = pytester.runpytest_subprocess('-c', 'other.ini', '--gremlins', *_NO_CATEGORIES)

    assert result.ret == 4, _output(result)
    assert '[tool] must be a table of settings, got 5' in _output(result)
