"""End-to-end tests: mutation testing runs only on a green baseline (issues #534, #540).

When test modules cannot be imported, no collected test backs a mutation verdict.
Running the mutation phase anyway printed a fake score such as ``Zapped: 2 gremlins
(100%)``. The plugin must instead skip the mutation phase, say why on stderr, and
leave pytest's own non-zero exit status in place.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

pytest.importorskip('xdist')

SAMPLE_SOURCE = "def classify(value: int) -> str:\n    if value == 0:\n        return 'zero'\n    return 'nonzero'\n"
BROKEN_TEST = 'from sample import classify\n\n\ndef test_zero():\n    assert classify(0) == "zero"\n'
WORKING_TEST = 'def test_arithmetic():\n    assert 1 + 1 == 2\n'
TARGETING_SAMPLE_PYPROJECT = '[tool.pytest-gremlins]\npaths = ["sample.py"]\n'
TESTS_CONFTEST = (
    'import pytest\n'
    '\n'
    'def pytest_configure(config):\n'
    "    config.addinivalue_line('markers', 'small: fast unit tests')\n"
    '\n'
    '\n'
    '@pytest.hookimpl(tryfirst=True)\n'
    'def pytest_collection_modifyitems(items):\n'
    '    for item in items:\n'
    '        item.add_marker(pytest.mark.small)\n'
)
SUBPROCESS_TIMEOUT_SECONDS = 300
SKIP_PREFIX = 'pytest-gremlins: skipping mutation testing because'
SKIP_MESSAGE = f'{SKIP_PREFIX} test collection failed'


def _write_project(pytester: pytest.Pytester, test_modules: dict[str, str]) -> None:
    """Write ``sample.py`` at the root and the given test modules under ``tests/``.

    ``sample`` is deliberately not importable from ``tests/``: there is no pytest
    ``pythonpath`` and no root conftest, so prepend import mode never puts the
    root on ``sys.path`` for the test modules.
    """
    pytester.makepyfile(sample=SAMPLE_SOURCE)
    pytester.makepyprojecttoml(TARGETING_SAMPLE_PYPROJECT)
    pytester.mkdir('tests')
    pytester.path.joinpath('tests', 'helpers.py').write_text('')
    pytester.path.joinpath('tests', 'conftest.py').write_text(TESTS_CONFTEST)
    for name, source in test_modules.items():
        pytester.path.joinpath('tests', name).write_text(source)


def _run_pytest_isolated(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in the project directory with neither the cwd nor ``PYTHONPATH`` on ``sys.path``.

    Plain ``python -m pytest`` puts the cwd on ``sys.path`` and ``Pytester.run`` exports the
    cwd as ``PYTHONPATH``; either makes ``sample`` importable and hides the collection
    error under test. ``-P`` (Python 3.11+) drops the cwd entry, and invoking the current
    interpreter avoids locating a platform-specific ``pytest`` console script.
    """
    environment = {name: value for name, value in os.environ.items() if name != 'PYTHONPATH'}
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, '-P', '-m', 'pytest', '-p', 'no:cacheprovider', *args],
        cwd=pytester.path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return pytest.RunResult(
        completed.returncode,
        completed.stdout.splitlines(),
        completed.stderr.splitlines(),
        time.perf_counter() - started,
    )


def _assert_no_mutation_report(result: pytest.RunResult) -> None:
    result.stdout.no_fnmatch_line('*mutation report*')
    result.stdout.no_fnmatch_line('*Zapped*')
    result.stdout.no_fnmatch_line('*Survived*')


@pytest.mark.medium
class DescribeCollectionErrorSkipsMutationTesting:
    """A baseline session with collection errors never reaches the mutation phase."""

    def it_prints_no_mutation_report_when_the_only_test_module_fails_to_import(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        _assert_no_mutation_report(result)

    def it_explains_the_skip_on_stderr(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s)); fix the collection errors first'])

    def it_keeps_pytests_non_zero_exit_status(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        assert result.ret == pytest.ExitCode.INTERRUPTED

    def it_skips_mutation_testing_on_partial_collection(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST, 'test_other.py': WORKING_TEST})

        result = _run_pytest_isolated(pytester, '--gremlins', '--continue-on-collection-errors', 'tests')

        _assert_no_mutation_report(result)
        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s))*'])
        assert result.ret == pytest.ExitCode.TESTS_FAILED

    def it_skips_mutation_testing_under_xdist(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST, 'test_other.py': WORKING_TEST})

        result = _run_pytest_isolated(
            pytester, '--gremlins', '-p', 'xdist', '-n', '2', '--continue-on-collection-errors', 'tests'
        )

        _assert_no_mutation_report(result)
        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s))*'])
        assert result.ret == pytest.ExitCode.TESTS_FAILED


@pytest.mark.medium
class DescribeCleanCollectionStillRunsMutationTesting:
    """Control: a suite that collects cleanly keeps its mutation report."""

    def it_prints_the_mutation_report(self, pytester: pytest.Pytester) -> None:
        _write_project(
            pytester,
            {'test_sample.py': BROKEN_TEST.replace('from sample', 'import sys\nsys.path.insert(0, ".")\nfrom sample')},
        )

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        result.stdout.fnmatch_lines(['*mutation report*'])
        assert SKIP_MESSAGE not in result.stderr.str()


CALC_SOURCE = 'def add(a, b):\n    return a + b\n'
RED_BASELINE_TEST = (
    'from calc import add\n'
    '\n'
    '\n'
    'def test_add_ignores_target():\n'
    '    assert add(1, 1) >= 0 or True\n'
    '    assert False, "unrelated broken test"\n'
)
GREEN_BASELINE_TEST = 'from calc import add\n\n\ndef test_add():\n    assert add(1, 1) == 2\n'
EXITING_TEST = 'import pytest\n\n\ndef test_exits():\n    pytest.exit("stop", returncode=3)\n'
IMPORTABLE_CALC_PYPROJECT = (
    '[tool.pytest-gremlins]\npaths = ["calc.py"]\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n'
)


def _write_calc_project(pytester: pytest.Pytester, test_source: str) -> None:
    """Write an importable ``calc.py`` target and one test module (collection succeeds)."""
    pytester.makepyfile(calc=CALC_SOURCE)
    pytester.makepyprojecttoml(IMPORTABLE_CALC_PYPROJECT)
    pytester.mkdir('tests')
    pytester.path.joinpath('tests', 'conftest.py').write_text(TESTS_CONFTEST)
    pytester.path.joinpath('tests', 'test_calc.py').write_text(test_source)


@pytest.mark.medium
class DescribeRedBaselineSkipsMutationTesting:
    """Failing baseline tests would count as kills for every gremlin they cover (issue #540)."""

    def it_prints_no_score_for_a_failing_baseline_test(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, RED_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        _assert_no_mutation_report(result)

    def it_names_the_failed_test_count_on_stderr(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, RED_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        result.stderr.fnmatch_lines([f'{SKIP_PREFIX} 1 baseline test(s) failed; mutation scores need a passing suite'])

    def it_keeps_pytests_failure_exit_status(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, RED_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        assert result.ret == pytest.ExitCode.TESTS_FAILED

    def it_skips_mutation_testing_for_a_failing_baseline_under_xdist(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, RED_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', '-p', 'xdist', '-n', '2', 'tests')

        _assert_no_mutation_report(result)
        result.stderr.fnmatch_lines([f'{SKIP_PREFIX} 1 baseline test(s) failed*'])
        assert result.ret == pytest.ExitCode.TESTS_FAILED


@pytest.mark.medium
class DescribeOtherNonGreenBaselinesSkipMutationTesting:
    """Every exit status other than OK skips mutation testing with an accurate reason."""

    def it_skips_when_no_tests_were_collected(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, GREEN_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', '-k', 'no_such_test', 'tests')

        _assert_no_mutation_report(result)
        result.stderr.fnmatch_lines([f'{SKIP_PREFIX} no tests were collected'])
        assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED

    def it_skips_with_the_exit_code_when_a_test_calls_pytest_exit(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, EXITING_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        _assert_no_mutation_report(result)
        result.stderr.fnmatch_lines([f'{SKIP_PREFIX} the baseline run ended with exit code 3'])
        assert result.ret == pytest.ExitCode.INTERNAL_ERROR

    def it_prints_only_the_collect_only_notice_under_collect_only(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, GREEN_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', '--collect-only', 'tests')

        assert result.stderr.str().count('skipping mutation testing') == 1
        result.stderr.fnmatch_lines(['pytest-gremlins: --collect-only detected, skipping mutation testing'])


@pytest.mark.medium
class DescribeGreenBaselineStillRunsMutationTesting:
    """Control: a passing suite keeps its mutation report."""

    def it_prints_the_mutation_report(self, pytester: pytest.Pytester) -> None:
        _write_calc_project(pytester, GREEN_BASELINE_TEST)

        result = _run_pytest_isolated(pytester, '--gremlins', 'tests')

        result.stdout.fnmatch_lines(['*mutation report*'])
        assert SKIP_PREFIX not in result.stderr.str()
