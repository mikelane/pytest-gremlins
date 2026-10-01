"""Real-coverage checks for #531's sysmon handling (Python 3.14+ only).

The unit tests in ``test_piggyback_registration.py`` feed ``_is_running_on_sysmon``
a mocked ``sys_info()``. These run real ``coverage.Coverage`` instances, so a coverage
release that renames the ``SysMonitor`` core or changes ``sys_info()`` breaks a test
instead of silently re-enabling context switching on sysmon.

Each probe runs in a fresh interpreter: starting a second tracer in-process would
displace the one measuring this test run.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.skipif(sys.version_info < (3, 14), reason='sysmon is the default coverage core only on Python 3.14+'),
]

CALC_MODULE_SOURCE = 'def add(a, b):\n    return a + b\n'
TWO_TESTS_SHARING_A_LINE = (
    'from calc import add\n\n\n'
    'def test_first():\n    assert add(1, 2) == 3\n\n\n'
    'def test_second():\n    assert add(2, 2) == 4\n'
)


def _run_probe(script: str, cwd: Path) -> str:
    completed = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class DescribeSysmonDetectionOnRealCoverage:
    """``_is_running_on_sysmon`` reads the core of a real, started instance."""

    def it_detects_sysmon_on_a_default_coverage_instance(self, tmp_path: Path) -> None:
        output = _run_probe(
            """
            import coverage
            from pytest_gremlins.plugin import _is_running_on_sysmon

            cov = coverage.Coverage(data_file=None)
            cov.start()
            detected = _is_running_on_sysmon(cov)
            cov.stop()
            print(detected)
            """,
            tmp_path,
        )

        assert output == 'True'

    def it_does_not_detect_sysmon_when_ctrace_is_requested(self, tmp_path: Path) -> None:
        output = _run_probe(
            """
            import coverage
            from pytest_gremlins.plugin import _is_running_on_sysmon

            cov = coverage.Coverage(data_file=None)
            cov.set_option('run:core', 'ctrace')
            cov.start()
            detected = _is_running_on_sysmon(cov)
            cov.stop()
            print(detected)
            """,
            tmp_path,
        )

        assert output == 'False'


class DescribePrivateModeCoreOnRealCoverage:
    """PRIVATE mode's own coverage instance measures with CTracer, not sysmon."""

    def it_starts_the_private_coverage_on_ctracer(self, tmp_path: Path) -> None:
        output = _run_probe(
            """
            from unittest.mock import MagicMock

            import pytest

            from pytest_gremlins.plugin import CoverageMode, GremlinSession, _set_session, pytest_sessionstart

            gremlin_session = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
            _set_session(gremlin_session)
            pytest_sessionstart(MagicMock(spec=pytest.Session))
            cov = gremlin_session.private_coverage
            cov.start()
            core = dict(cov.sys_info())['core']
            cov.stop()
            print(core)
            """,
            tmp_path,
        )

        assert output == 'CTracer'


class DescribePiggybackRunWithWarningsAsErrors:
    """``--gremlins --cov`` completes under ``filterwarnings = error`` on sysmon."""

    def it_completes_a_mutation_run_without_errors(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=CALC_MODULE_SOURCE, test_calc=TWO_TESTS_SHARING_A_LINE)
        pytester_with_markers.makeini('[pytest]\npythonpath = .\nfilterwarnings =\n    error\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=calc.py', '--cov=.')

        assert result.ret == pytest.ExitCode.OK
        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*', 'Zapped: *'])
