"""The coverage pre-scan limit covers the rerun delay of every flaky test the baseline saw (issue #673)."""

from __future__ import annotations

import pytest

pytest_plugins = ['pytester']

_SOURCE = 'def add(a, b):\n    return a + b\n'

_TESTS = """
import os
import pathlib

from calc import add

MARK_DIR = pathlib.Path(os.environ['FLAKY_MARK_DIR'])


def _fail_on_first_attempt_in_this_process(name):
    flag = MARK_DIR / f'{name}-{os.getpid()}'
    if not flag.exists():
        flag.write_text('x')
        raise AssertionError('flaky first attempt')


def test_add():
    assert add(2, 3) == 5


def test_flaky_0():
    _fail_on_first_attempt_in_this_process('f0')


def test_flaky_1():
    _fail_on_first_attempt_in_this_process('f1')


def test_flaky_2():
    _fail_on_first_attempt_in_this_process('f2')
"""


@pytest.mark.large
def it_does_not_time_out_the_pre_scan_when_three_flaky_tests_wait_out_the_rerun_delay(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Three flaky tests each sleep --reruns-delay (6s) once: 18s of sleeps. One test's share alone
    # gives a limit of 5 * 2 + 6 = 16s, shorter than the sleeps; three tests' share gives 28s.
    pytester.makepyfile(calc=_SOURCE, test_calc=_TESTS)
    pytester.makeini('[pytest]\n')
    mark_dir = pytester.mkdir('marks')
    monkeypatch.setenv('FLAKY_MARK_DIR', str(mark_dir))
    monkeypatch.setenv('PYTHONPATH', str(pytester.path))

    result = pytester.runpytest_subprocess(
        '-p',
        'no:cacheprovider',
        '--gremlins',
        '--gremlin-targets=calc.py',
        '--gremlin-coverage-timeout',
        '5',
        '--reruns',
        '1',
        '--reruns-delay',
        '6',
        '-W',
        'default',
        timeout=600,
    )

    assert 'coverage pre-scan exceeded' not in result.stdout.str() + result.stderr.str()
