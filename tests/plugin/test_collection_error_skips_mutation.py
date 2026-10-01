"""End-to-end tests: a failed baseline collection must skip mutation testing (issue #534).

When test modules cannot be imported, no collected test backs a mutation verdict.
Running the mutation phase anyway printed a fake score such as ``Zapped: 2 gremlins
(100%)``. The plugin must instead skip the mutation phase, say why on stderr, and
leave pytest's own non-zero exit status in place.
"""

from __future__ import annotations

import os
from pathlib import Path
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
SKIP_MESSAGE = 'pytest-gremlins: skipping mutation testing because test collection failed'
MUTATION_OUTPUT_MARKERS = ('Zapped', 'Survived', 'mutation report')


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


def _run_pytest_script(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run the ``pytest`` console script in the project directory with a clean ``PYTHONPATH``.

    ``python -m pytest`` puts the cwd on ``sys.path`` and ``Pytester.run`` exports the
    cwd as ``PYTHONPATH``; either makes ``sample`` importable and hides the collection
    error under test.
    """
    environment = {name: value for name, value in os.environ.items() if name != 'PYTHONPATH'}
    started = time.perf_counter()
    completed = subprocess.run(
        [str(Path(sys.executable).with_name('pytest')), '-p', 'no:cacheprovider', *args],
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


@pytest.mark.medium
class DescribeCollectionErrorSkipsMutationTesting:
    """A baseline session with collection errors never reaches the mutation phase."""

    def it_prints_no_mutation_report_when_the_only_test_module_fails_to_import(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_script(pytester, '--gremlins', 'tests')

        output = result.stdout.str()
        assert [marker for marker in MUTATION_OUTPUT_MARKERS if marker in output] == []

    def it_explains_the_skip_on_stderr(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_script(pytester, '--gremlins', 'tests')

        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s)); fix the collection errors first'])

    def it_keeps_pytests_non_zero_exit_status(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST})

        result = _run_pytest_script(pytester, '--gremlins', 'tests')

        assert result.ret == pytest.ExitCode.INTERRUPTED

    def it_skips_mutation_testing_on_partial_collection(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST, 'test_other.py': WORKING_TEST})

        result = _run_pytest_script(pytester, '--gremlins', '--continue-on-collection-errors', 'tests')

        output = result.stdout.str()
        assert [marker for marker in MUTATION_OUTPUT_MARKERS if marker in output] == []
        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s))*'])
        assert result.ret != 0

    def it_skips_mutation_testing_under_xdist(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, {'test_sample.py': BROKEN_TEST, 'test_other.py': WORKING_TEST})

        result = _run_pytest_script(
            pytester, '--gremlins', '-p', 'xdist', '-n', '2', '--continue-on-collection-errors', 'tests'
        )

        output = result.stdout.str()
        assert [marker for marker in MUTATION_OUTPUT_MARKERS if marker in output] == []
        result.stderr.fnmatch_lines([f'{SKIP_MESSAGE} (1 error(s))*'])
        assert result.ret != 0


@pytest.mark.medium
class DescribeCleanCollectionStillRunsMutationTesting:
    """Control: a suite that collects cleanly keeps its mutation report."""

    def it_prints_the_mutation_report(self, pytester: pytest.Pytester) -> None:
        _write_project(
            pytester,
            {'test_sample.py': BROKEN_TEST.replace('from sample', 'import sys\nsys.path.insert(0, ".")\nfrom sample')},
        )

        result = _run_pytest_script(pytester, '--gremlins', 'tests')

        result.stdout.fnmatch_lines(['*mutation report*'])
        assert SKIP_MESSAGE not in result.stderr.str()
