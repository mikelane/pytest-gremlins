"""Per-mutant verdicts must come from running the covering test, whatever its style.

The lightweight runner calls test functions as bare callables. Async, parametrized
and fixture-taking tests cannot be run that way, so gremlins selecting them must run
through the full pytest bootstrap, and a test that never ran must never decide a
verdict (issue #486).

The four-style repro and the fixture-taking "says nothing" cases are modelled on the
fidelity tests in PR #522 by fwilkerson-cn.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

_TARGET = """
def plain_flag(code):
    if code < 400:
        return 'ok'
    return 'err'


async def async_flag(code):
    if code < 400:
        return 'ok'
    return 'err'


def param_flag(code):
    if code < 400:
        return 'ok'
    return 'err'


def fixture_flag(code):
    if code < 400:
        return 'ok'
    return 'err'
"""

_FOUR_STYLE_TESTS = """
import os

import pytest
from sample import async_flag, fixture_flag, param_flag, plain_flag

LOG = '__LOG__'


def _sentinel(style):
    with open(LOG, 'a') as handle:
        handle.write(style + '\\t' + os.environ.get('ACTIVE_GREMLIN', 'NONE') + '\\n')


def test_plain():
    _sentinel('plain')
    assert plain_flag(399) == 'ok'
    assert plain_flag(400) == 'err'


async def test_async():
    _sentinel('async')
    assert await async_flag(399) == 'ok'
    assert await async_flag(400) == 'err'


@pytest.mark.parametrize('variant', ['first', 'second'])
def test_param(variant):
    _sentinel('param')
    assert param_flag(399) == 'ok'
    assert param_flag(400) == 'err'


def test_fixture(tmp_path):
    _sentinel('fixture')
    assert fixture_flag(399) == 'ok'
    assert fixture_flag(400) == 'err'
"""

_RUN_COROUTINES_CONFTEST = """
import asyncio
import inspect

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**arguments))
        return True
    return None
"""

_SIMPLE_TARGET = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

_SAYS_NOTHING = {
    'fixture': """
        def test_says_nothing(tmp_path):
            assert tmp_path.is_dir()
        """,
    'parametrized': """
        import pytest

        @pytest.mark.parametrize('n', [1, 2, 3])
        def test_says_nothing(n):
            assert n > 0
        """,
}

_CATCHES = """
import pytest
from sample import classify

def test_covers(tmp_path):
    assert tmp_path.is_dir()
    assert classify(11) == 'big'
    assert classify(10) == 'small'
    assert classify(1) == 'small'
"""

_COMMON_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Timeout', 'Error')}


def _run(pytester: pytest.Pytester, target: str, tests: str, *extra_args: str) -> dict[str, int]:
    pytester.makepyfile(sample=target)
    pytester.makepyfile(test_sample=tests)
    result = pytester.runpytest_subprocess(*_COMMON_ARGS, *extra_args)
    return _verdicts(result.stdout.str())


def _styles_run_against_a_mutant(log: Path) -> set[str]:
    rows = [line.split('\t') for line in log.read_text().splitlines()]
    return {style for style, mutant in rows if mutant != 'NONE'}


@pytest.fixture
def pytester_running_coroutines(pytester_with_markers: pytest.Pytester) -> pytest.Pytester:
    existing = pytester_with_markers.path.joinpath('conftest.py').read_text()
    pytester_with_markers.makeconftest(existing + _RUN_COROUTINES_CONFTEST)
    return pytester_with_markers


@pytest.mark.medium
class DescribeFourStyleFidelity:
    """Identical targets covered by plain, async, parametrized and fixture tests are all genuinely zapped."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_zaps_every_mutant_whatever_the_test_style(
        self,
        pytester_running_coroutines: pytest.Pytester,
        mode: str,
    ) -> None:
        log = pytester_running_coroutines.path / 'ran.log'
        tests = _FOUR_STYLE_TESTS.replace('__LOG__', log.as_posix())

        verdicts = _run(pytester_running_coroutines, _TARGET, tests, *_EXECUTION_MODES[mode])

        assert verdicts['Survived'] == 0
        assert verdicts['Error'] == 0
        assert verdicts['Zapped'] > 0

    def it_runs_every_style_of_test_body_against_a_mutant(self, pytester_running_coroutines: pytest.Pytester) -> None:
        log = pytester_running_coroutines.path / 'ran.log'
        tests = _FOUR_STYLE_TESTS.replace('__LOG__', log.as_posix())

        _run(pytester_running_coroutines, _TARGET, tests)

        assert _styles_run_against_a_mutant(log) == {'plain', 'async', 'param', 'fixture'}


@pytest.mark.medium
class DescribeTestsThatSayNothing:
    """A test the runner cannot execute no longer scores a kill for a target it never touches."""

    @pytest.mark.parametrize('case', list(_SAYS_NOTHING))
    def it_leaves_every_mutant_survived(self, pytester_with_markers: pytest.Pytester, case: str) -> None:
        verdicts = _run(
            pytester_with_markers,
            _SIMPLE_TARGET,
            _SAYS_NOTHING[case],
            '--gremlin-no-coverage-filter',
        )

        assert verdicts['Zapped'] == 0
        assert verdicts['Survived'] > 0

    def it_still_zaps_with_a_fixture_taking_test_that_covers_the_target(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        verdicts = _run(pytester_with_markers, _SIMPLE_TARGET, _CATCHES, '--gremlin-no-coverage-filter')

        assert verdicts['Zapped'] > 0
        assert verdicts['Survived'] == 0


_HOOK_CONFTEST = """
import builtins


def pytest_runtest_setup(item):
    builtins.HOOK_PREPARED = True
"""

_NEEDS_THE_HOOK = """
from sample import classify

def test_needs_the_hook():
    assert HOOK_PREPARED is True
    classify(11)
"""


@pytest.mark.medium
class DescribeTestsPreparedByConftestHooks:
    """A conftest hook runs around a plain test but is invisible in its fixture names."""

    def it_does_not_count_a_hook_dependent_test_as_a_kill(self, pytester_with_markers: pytest.Pytester) -> None:
        existing = pytester_with_markers.path.joinpath('conftest.py').read_text()
        pytester_with_markers.makeconftest(existing + _HOOK_CONFTEST)

        verdicts = _run(pytester_with_markers, _SIMPLE_TARGET, _NEEDS_THE_HOOK, '--gremlin-no-coverage-filter')

        assert verdicts['Zapped'] == 0
        assert verdicts['Survived'] > 0
