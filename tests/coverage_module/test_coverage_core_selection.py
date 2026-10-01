"""Regression tests for #531: the pre-scan must not run on coverage's sysmon core.

On Python 3.14 coverage defaults to the ``sysmon`` core, which drops contexts set
through ``Coverage.switch_context``. Each line is then credited only to the first
test that ran it, so gremlin test selection under-picks and reports false survivors.
The generated rc therefore pins ``core = ctrace`` and the subprocess env must not
carry a user-set ``COVERAGE_CORE`` that would override it.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage

CALC_MODULE_SOURCE = 'def add(a, b):\n    return a + b\n'
_RETURN_LINE = 2
TWO_TESTS_SHARING_A_LINE = (
    'from calc import add\n\n\n'
    'def test_first():\n    assert add(1, 2) == 3\n\n\n'
    'def test_second():\n    assert add(2, 2) == 4\n'
)

# sysmon became coverage's default core on 3.14; sys.monitoring itself exists from 3.12.
sysmon_is_default_core = pytest.mark.skipif(
    sys.version_info < (3, 14), reason='sysmon is the default coverage core only on Python 3.14+'
)
sysmon_is_available = pytest.mark.skipif(
    sys.version_info < (3, 12), reason='sys.monitoring exists only on Python 3.12+'
)


def _write_project(root: Path, *, extra_pytest_ini: str = '') -> None:
    (root / 'calc.py').write_text(CALC_MODULE_SOURCE)
    (root / 'test_calc.py').write_text(TWO_TESTS_SHARING_A_LINE)
    (root / 'pytest.ini').write_text(f'[pytest]\npythonpath = .\n{extra_pytest_ini}')


def _contexts_covering_return_line(coverage_by_test: dict[str, dict[str, list[int]]]) -> set[str]:
    return {test for test, files in coverage_by_test.items() if any(_RETURN_LINE in lines for lines in files.values())}


@pytest.mark.medium
class DescribePerTestAttribution:
    """Two tests executing the same line both appear as contexts for it.

    These end-to-end checks only discriminate where sysmon would otherwise be used:
    the default-core cases need Python 3.14+, the ``COVERAGE_CORE=sysmon`` case 3.12+.
    On older versions they would pass with the fix removed, so they are skipped there;
    the rc and env unit tests below still guard every version.
    """

    @sysmon_is_default_core
    def it_attributes_a_shared_line_to_every_test_that_runs_it(self, tmp_path: Path) -> None:
        _write_project(tmp_path)

        coverage_by_test = _run_tests_with_coverage(
            ['test_calc.py::test_first', 'test_calc.py::test_second'],
            tmp_path,
        )

        assert _contexts_covering_return_line(coverage_by_test) == {
            'test_calc.py::test_first',
            'test_calc.py::test_second',
        }

    @sysmon_is_available
    def it_ignores_a_user_set_coverage_core_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_project(tmp_path)
        monkeypatch.setenv('COVERAGE_CORE', 'sysmon')

        coverage_by_test = _run_tests_with_coverage(
            ['test_calc.py::test_first', 'test_calc.py::test_second'],
            tmp_path,
        )

        assert _contexts_covering_return_line(coverage_by_test) == {
            'test_calc.py::test_first',
            'test_calc.py::test_second',
        }

    @sysmon_is_default_core
    def it_attributes_a_shared_line_to_both_tests_when_warnings_are_errors(self, tmp_path: Path) -> None:
        _write_project(tmp_path, extra_pytest_ini='filterwarnings =\n    error\n    ignore::pytest.PytestWarning\n')

        coverage_by_test = _run_tests_with_coverage(
            ['test_calc.py::test_first', 'test_calc.py::test_second'],
            tmp_path,
        )

        assert _contexts_covering_return_line(coverage_by_test) == {
            'test_calc.py::test_first',
            'test_calc.py::test_second',
        }


@pytest.mark.medium
class DescribeGeneratedCoverageRc:
    """The generated rc pins the ctrace core in both include/source branches."""

    @pytest.mark.parametrize('coverage_include', [None, ['/some/path/mod.py']])
    def it_pins_the_ctrace_core(self, tmp_path: Path, coverage_include: list[str] | None) -> None:
        captured: list[str] = []

        def capture_rc(*_args: object, **_kwargs: object) -> None:
            captured.append((tmp_path / '.coveragerc.gremlins').read_text())

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_rc):
            _run_tests_with_coverage(['t.py::test_a'], tmp_path, coverage_include=coverage_include)

        assert 'core = ctrace' in captured[0]


@pytest.mark.medium
class DescribeSubprocessEnvironment:
    """COVERAGE_CORE and COVERAGE_FILE never reach the pre-scan subprocess.

    Assertions bind single values to locals first: pytest's assertion rewriting would
    otherwise print the whole forwarded environment, secrets included, on failure.
    """

    def it_strips_coverage_core_from_the_subprocess_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('COVERAGE_CORE', 'sysmon')
        fake_run = create_autospec(subprocess.run)

        with patch('pytest_gremlins.plugin.subprocess.run', fake_run):
            _run_tests_with_coverage(['t.py::test_a'], tmp_path)

        forwards_coverage_core = 'COVERAGE_CORE' in fake_run.call_args.kwargs['env']
        assert not forwards_coverage_core

    def it_strips_coverage_file_from_the_subprocess_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('COVERAGE_FILE', str(tmp_path / 'ci-coverage.db'))
        fake_run = create_autospec(subprocess.run)

        with patch('pytest_gremlins.plugin.subprocess.run', fake_run):
            _run_tests_with_coverage(['t.py::test_a'], tmp_path)

        forwards_coverage_file = 'COVERAGE_FILE' in fake_run.call_args.kwargs['env']
        assert not forwards_coverage_file

    def it_preserves_the_rest_of_the_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('GREMLINS_531_MARKER', 'kept')
        fake_run = create_autospec(subprocess.run)

        with patch('pytest_gremlins.plugin.subprocess.run', fake_run):
            _run_tests_with_coverage(['t.py::test_a'], tmp_path)

        forwarded_marker = fake_run.call_args.kwargs['env'].get('GREMLINS_531_MARKER')
        forwarded_path = fake_run.call_args.kwargs['env'].get('PATH')
        expected_path = os.environ.get('PATH')
        assert forwarded_marker == 'kept'
        assert forwarded_path == expected_path
