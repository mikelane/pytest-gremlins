"""A cached verdict reflects the rerun filter the gremlin runs read, with or without ``-c`` (#677, #951).

A ``rerun_except`` pattern that ``-o`` cannot carry unchanged (trailing space) used to be reset to empty for the
gremlin runs of a ``-c`` session, so they ran with no filter.  Gremlin runs are now given the ``-c`` file itself, so
they apply the filter exactly as a run without ``-c`` does, and both reach the same verdict.
"""

from __future__ import annotations

import pytest

CALC = 'def add(a, b):\n    return a + b\n'
# Fails once under a mutation with a message the 'xyz ' pattern matches, then passes on the rerun.
FLAKY_UNDER_MUTATION = (
    'from calc import add\n\n\n'
    'def test_add(request):\n'
    "    if add(2, 3) != 5 and getattr(request.node, 'execution_count', 1) == 1:\n"
    "        raise ConnectionError('flaky boom xyz ')\n"
)
PYPROJECT = '[tool.pytest.ini_options]\nrerun_except = ["xyz "]\n'
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=calc.py', '--gremlin-cache', '--reruns', '1')


def _project(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(calc=CALC, test_calc=FLAKY_UNDER_MUTATION)
    pytester.makefile('.toml', pyproject=PYPROJECT)


@pytest.mark.medium
@pytest.mark.parametrize(
    ('config_args', 'expected'),
    [((), 'Zapped: 2 gremlins*'), (('-c', 'pyproject.toml'), 'Zapped: 2 gremlins*')],
)
def it_cold_run_reaches_the_verdict_its_gremlin_runs_earn(
    pytester: pytest.Pytester, config_args: tuple[str, ...], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-clear-cache', *config_args)

    result.stdout.fnmatch_lines([expected])


@pytest.mark.medium
def it_discovered_config_run_reaches_the_verdict_of_a_dash_c_run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)
    pytester.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'pyproject.toml')

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS)

    result.stdout.fnmatch_lines(['Zapped: 2 gremlins*'])


@pytest.mark.medium
def it_dash_c_run_reaches_the_verdict_of_a_discovered_config_run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)
    pytester.runpytest_subprocess(*GREMLIN_ARGS)

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'pyproject.toml')

    result.stdout.fnmatch_lines(['Zapped: 2 gremlins*'])
