"""The outer xdist worker's identity must not leak into the tests it runs (issue #1016).

The suite runs under ``pytest -n`` in CI. xdist exports ``PYTEST_XDIST_WORKER``, ``PYTEST_XDIST_WORKER_COUNT``
and ``PYTEST_XDIST_TESTRUNUID`` into every worker process. Pytester runs and subprocess children inherit them, and
pytest-test-categories decides "I am an xdist worker" from that variable alone, so an inner session would take the
worker path and the ``xdist_integration`` tests would exercise the wrong code.
"""

from __future__ import annotations

import os
import sys

import pytest

XDIST_WORKER_ENV_NAMES = ('PYTEST_XDIST_WORKER', 'PYTEST_XDIST_WORKER_COUNT', 'PYTEST_XDIST_TESTRUNUID')

_PRINT_XDIST_ENV = (
    'import os\n'
    f'names = {XDIST_WORKER_ENV_NAMES!r}\n'
    "print('LEAKED=' + ','.join(name for name in names if name in os.environ))\n"
)


@pytest.mark.small
class DescribeXdistWorkerEnvIsolation:
    """A test never sees the xdist worker variables of the process that runs it."""

    @pytest.mark.parametrize('name', XDIST_WORKER_ENV_NAMES)
    def it_hides_the_outer_worker_variable_from_the_test(self, name: str) -> None:
        assert name not in os.environ

    @pytest.mark.parametrize('name', XDIST_WORKER_ENV_NAMES)
    def it_restores_nothing_a_test_sets_itself(self, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(name, 'set-by-the-test')

        assert os.environ[name] == 'set-by-the-test'


@pytest.mark.medium
class DescribeXdistWorkerEnvInChildren:
    """Children of a test do not inherit the outer worker's xdist variables."""

    def it_keeps_the_variables_out_of_a_pytester_subprocess(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(test_child=_PRINT_XDIST_ENV + 'def test_child():\n    pass\n')

        result = pytester.runpytest_subprocess('-s', '-p', 'no:randomly')

        result.stdout.fnmatch_lines(['*LEAKED=', '*1 passed*'])

    def it_keeps_the_variables_out_of_a_plain_subprocess(self) -> None:
        import subprocess  # noqa: PLC0415

        completed = subprocess.run(
            [sys.executable, '-c', _PRINT_XDIST_ENV],
            capture_output=True,
            text=True,
            check=True,
        )

        assert completed.stdout.strip() == 'LEAKED='
