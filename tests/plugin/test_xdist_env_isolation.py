"""The outer xdist worker's identity must not leak into the tests it runs (issue #1016).

The suite runs under ``pytest -n`` in CI. xdist exports ``PYTEST_XDIST_WORKER``, ``PYTEST_XDIST_WORKER_COUNT``
and ``PYTEST_XDIST_TESTRUNUID`` into every worker process. Pytester runs and subprocess children inherit them, and
pytest-test-categories decides "I am an xdist worker" from that variable alone, so an inner session would take the
worker path and the ``xdist_integration`` tests would exercise the wrong code.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from xdist_env import XDIST_WORKER_ENV_NAMES  # type: ignore[import-not-found]

_TESTS_DIR = Path(__file__).parents[1]

_PRINT_XDIST_ENV = (
    'import os\n'
    f'names = {XDIST_WORKER_ENV_NAMES!r}\n'
    "print('LEAKED=' + ','.join(name for name in names if name in os.environ))\n"
)

_INNER_CONFTEST = 'from xdist_env import hide_outer_xdist_worker_env  # noqa: F401\n'
_INNER_TEST = (
    'import os\n\n'
    'from xdist_env import XDIST_WORKER_ENV_NAMES\n\n\n'
    'def test_sees_no_worker_variable():\n'
    '    assert [name for name in XDIST_WORKER_ENV_NAMES if os.getenv(name) is not None] == []\n'
)


@pytest.fixture
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest sessions write UTF-8, so the Windows cp1252 bullets pytester decodes as UTF-8 survive."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


def _export_outer_worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give a child the environment an xdist worker has, and let its conftest import the shared helper."""
    for name in XDIST_WORKER_ENV_NAMES:
        monkeypatch.setenv(name, 'outer-worker')
    monkeypatch.setenv('PYTHONPATH', str(_TESTS_DIR))


@pytest.mark.small
class DescribeXdistWorkerEnvIsolation:
    """A test never sees the xdist worker variables of the process that runs it.

    These in-process checks can only fail when the outer run is under ``-n``; in a serial run the variables never
    exist. ``DescribeXdistWorkerEnvScrub`` proves the scrub itself regardless of how the outer run was started.
    """

    @pytest.mark.parametrize('name', XDIST_WORKER_ENV_NAMES)
    def it_hides_the_outer_worker_variable_from_the_test(self, name: str) -> None:
        is_visible = name in os.environ

        assert is_visible is False


@pytest.mark.medium
class DescribeXdistWorkerEnvScrub:
    """The scrub fixture removes the worker variables even when the outer run is serial."""

    @pytest.mark.usefixtures('utf8_child_output')
    def it_hides_variables_set_in_the_environment_from_an_inner_test(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _export_outer_worker_env(monkeypatch)
        pytester.makeconftest(_INNER_CONFTEST)
        pytester.makepyfile(test_inner=_INNER_TEST)

        result = pytester.runpytest_subprocess('-p', 'no:randomly', '-p', 'no:xdist')

        result.assert_outcomes(passed=1)


@pytest.mark.medium
class DescribeXdistWorkerEnvInChildren:
    """Children of a test do not inherit the outer worker's xdist variables.

    Like the in-process checks above, these only fail when the outer run is under ``-n``.
    """

    @pytest.mark.usefixtures('utf8_child_output')
    def it_keeps_the_variables_out_of_a_pytester_subprocess(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(test_child=_PRINT_XDIST_ENV + 'def test_child():\n    pass\n')

        result = pytester.runpytest_subprocess('-s', '-p', 'no:randomly')

        result.stdout.fnmatch_lines(['*LEAKED=', '*1 passed*'])

    def it_keeps_the_variables_out_of_a_plain_subprocess(self) -> None:
        completed = subprocess.run(
            [sys.executable, '-c', _PRINT_XDIST_ENV],
            capture_output=True,
            text=True,
            check=True,
        )

        assert completed.stdout.strip() == 'LEAKED='
