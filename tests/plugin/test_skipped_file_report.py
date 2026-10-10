"""End-to-end tests: source files skipped because instrumentation failed are reported (issue #638).

``transform_source`` raising used to drop the whole file with only a captured log record, so a sole
skipped target read as a clean ``No gremlins found``. The skip must reach the terminal with the file
and the reason, and a run where nothing was instrumented must say so.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

pytest.importorskip('xdist')

RunPytestIsolated = Callable[..., pytest.RunResult]

CHAIN_TERMS = 130
CHAIN_SOURCE = 'def big(x):\n    return ' + ' + '.join(['x'] * CHAIN_TERMS) + '\n'
AGE_SOURCE = 'def is_adult(age):\n    return age >= 18\n'
CHAIN_TEST = 'from demo.chain import big\n\n\ndef test_big():\n    assert big(1) == 130\n'
AGE_TEST = 'from demo.age import is_adult\n\n\ndef test_is_adult():\n    assert is_adult(20)\n'
PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["src"]\n'
WARNINGS_AS_ERRORS_PYPROJECT = PYPROJECT + 'filterwarnings = ["error"]\n'
SKIP_LINE = 'pytest-gremlins: skipped *chain.py: could not instrument (RecursionError: *)'
TESTS_CONFTEST = (
    'import pytest\n'
    '\n'
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


def _write_project(pytester: pytest.Pytester, *, with_age: bool, pyproject: str = PYPROJECT) -> None:
    pytester.makepyprojecttoml(pyproject)
    pytester.mkdir('src')
    pytester.mkdir('src/demo')
    pytester.path.joinpath('src', 'demo', '__init__.py').write_text('')
    pytester.path.joinpath('src', 'demo', 'chain.py').write_text(CHAIN_SOURCE)
    pytester.mkdir('tests')
    pytester.path.joinpath('tests', 'conftest.py').write_text(TESTS_CONFTEST)
    pytester.path.joinpath('tests', 'test_chain.py').write_text(CHAIN_TEST)
    if with_age:
        pytester.path.joinpath('src', 'demo', 'age.py').write_text(AGE_SOURCE)
        pytester.path.joinpath('tests', 'test_age.py').write_text(AGE_TEST)


def _skip_message_count(result: pytest.RunResult) -> int:
    return sum('pytest-gremlins: skipped' in line and 'chain.py' in line for line in result.stdout.lines)


@pytest.mark.medium
class DescribeSkippedFileReport:
    """A file that fails to instrument is named on the terminal with the reason."""

    def it_names_the_skipped_file_and_the_exception_type(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, with_age=True)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo')

        result.stdout.fnmatch_lines([SKIP_LINE])

    def it_still_reports_gremlins_from_the_file_that_instruments(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, with_age=True)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo')

        result.stdout.fnmatch_lines(['*age.py*'])

    def it_names_the_skipped_file_when_warnings_are_errors(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, with_age=True, pyproject=WARNINGS_AS_ERRORS_PYPROJECT)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo')

        result.stdout.fnmatch_lines([SKIP_LINE, '*Zapped*'])

    @pytest.mark.parametrize('parallel_option', [['--gremlin-parallel'], ['-p', 'xdist', '-n', '2']])
    def it_prints_one_skip_message_per_file_under_parallel_execution(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated, parallel_option: list[str]
    ) -> None:
        _write_project(pytester, with_age=True)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo', *parallel_option)

        assert _skip_message_count(result) == 1

    def it_does_not_present_a_run_with_only_a_skipped_target_as_clean(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, with_age=False)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo')

        result.stdout.fnmatch_lines(['*1 file(s) skipped and not mutation tested*', '*chain.py*'])
        result.stdout.no_fnmatch_line('*No gremlins found in source code*')


@pytest.mark.medium
class DescribeAnyInstrumentationFailureIsReported:
    """Every exception from ``transform_source`` is reported, not only ``RecursionError``."""

    def it_reports_a_value_error_with_its_message(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise ValueError('boom')

        monkeypatch.setattr('pytest_gremlins.plugin.transform_source', explode)
        _write_project(pytester, with_age=False)

        result = pytester.runpytest_inprocess('--gremlins', '--gremlin-targets', 'src/demo')

        result.stdout.fnmatch_lines(['pytest-gremlins: skipped *chain.py: could not instrument (ValueError: boom)'])
