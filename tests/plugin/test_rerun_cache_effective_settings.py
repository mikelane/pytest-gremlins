"""A cached verdict is not reused across runs whose gremlin runs used different rerun filters (#677).

Under ``-c``, a ``rerun_except`` pattern that ``-o`` cannot carry unchanged (trailing space) is reset to empty
for the gremlin runs, so they run with no filter.  Without ``-c`` the gremlin runs discover the same file and
apply the filter.  The main session resolves the same ``rerun_except`` both times, so the cache key is equal
and the second run reuses verdicts the first run's gremlin runs reached under different settings.
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
    [((), 'Zapped: 2 gremlins*'), (('-c', 'pyproject.toml'), 'Survived: 2 gremlins*')],
)
def it_cold_run_reaches_the_verdict_its_gremlin_runs_earn(
    pytester: pytest.Pytester, config_args: tuple[str, ...], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-clear-cache', *config_args)

    result.stdout.fnmatch_lines([expected])


@pytest.mark.medium
def it_discovered_config_run_does_not_reuse_survivors_from_a_dash_c_run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)
    pytester.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'pyproject.toml')

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS)

    result.stdout.fnmatch_lines(['Zapped: 2 gremlins*'])


@pytest.mark.medium
def it_dash_c_run_does_not_reuse_zaps_from_a_discovered_config_run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    _project(pytester)
    pytester.runpytest_subprocess(*GREMLIN_ARGS)

    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'pyproject.toml')

    result.stdout.fnmatch_lines(['Survived: 2 gremlins*'])
