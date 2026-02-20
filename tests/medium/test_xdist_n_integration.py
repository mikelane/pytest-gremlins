"""Integration tests for xdist -n flag integration.

These tests verify that passing -n to pytest-xdist configures pytest-gremlins'
parallel worker pool, and that the old --gremlin-parallel / --gremlin-workers
flags emit a deprecation warning when xdist is available.

Note on xdist + gremlins interaction: xdist resolves 'auto' to the actual CPU
count before our pytest_configure hook runs, so GremlinSession.parallel_workers
receives the integer CPU count when -n auto is used.

Config wiring tests use runpytest (subprocess). A conftest injected into the
pytester directory hooks pytest_sessionfinish to write GremlinSession.parallel_*
values to a JSON file before the process exits. The outer test then reads that
file to assert the correct wiring — avoiding the module-global-reset problem that
occurs with runpytest_inprocess.
"""

from __future__ import annotations

import json

import pytest


_INSPECT_OUTPUT_FILENAME = '_gremlins_inspect.json'

_INSPECTOR_CONFTEST = f'''
import json
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Write parallel config to a known filename so the outer test can read it."""
    from pytest_gremlins.plugin import _get_session
    gs = _get_session()
    if gs is None:
        data = {{'enabled': None, 'parallel_enabled': None, 'parallel_workers': None}}
    else:
        data = {{
            'enabled': gs.enabled,
            'parallel_enabled': gs.parallel_enabled,
            'parallel_workers': gs.parallel_workers,
        }}
    output = Path(session.config.rootdir) / '{_INSPECT_OUTPUT_FILENAME}'
    output.write_text(json.dumps(data), encoding='utf-8')
'''


def _run_with_inspect(
    pytester: pytest.Pytester,
    *args: str,
) -> dict[str, object]:
    """Run pytest subprocess and return the captured GremlinSession parallel config.

    Injects an inspector conftest that writes GremlinSession.parallel_* to a JSON
    file during pytest_sessionfinish (before pytest_unconfigure clears the global).
    The outer test reads from that file after the subprocess exits.
    """
    output_file = pytester.path / _INSPECT_OUTPUT_FILENAME
    pytester.makeconftest(_INSPECTOR_CONFTEST)
    result = pytester.runpytest_subprocess(*args)
    result.assert_outcomes(passed=1)
    assert output_file.exists(), f'Inspector conftest did not write output file; stdout:\n{result.stdout.str()}'
    return json.loads(output_file.read_text(encoding='utf-8'))


@pytest.mark.medium
class TestXdistNFlagWiresParallelConfig:
    """Tests that -n auto and -n N set the correct GremlinSession parallel config.

    Uses subprocess pytest (runpytest) with an inspector conftest that writes
    GremlinSession.parallel_* to a JSON file during pytest_sessionfinish — before
    the module global is cleared by pytest_unconfigure.
    """

    def test_n_auto_sets_parallel_enabled_true(self, pytester: pytest.Pytester) -> None:
        """-n auto sets parallel_enabled=True on GremlinSession."""
        pytester.makepyfile(sample='def add(a, b):\n    return a + b\n')
        pytester.makepyfile(test_sample='from sample import add\ndef test_add():\n    assert add(1, 2) == 3\n')

        data = _run_with_inspect(
            pytester,
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-n',
            'auto',
        )

        assert data['parallel_enabled'] is True

    def test_n_integer_sets_parallel_enabled_true(self, pytester: pytest.Pytester) -> None:
        """-n 2 sets parallel_enabled=True on GremlinSession."""
        pytester.makepyfile(sample='def subtract(a, b):\n    return a - b\n')
        pytester.makepyfile(
            test_sample='from sample import subtract\ndef test_subtract():\n    assert subtract(5, 3) == 2\n'
        )

        data = _run_with_inspect(
            pytester,
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-n',
            '2',
        )

        assert data['parallel_enabled'] is True

    def test_n_integer_sets_parallel_workers_to_that_count(self, pytester: pytest.Pytester) -> None:
        """-n 2 sets parallel_workers=2 on GremlinSession — not None, not 4."""
        pytester.makepyfile(sample='def subtract(a, b):\n    return a - b\n')
        pytester.makepyfile(
            test_sample='from sample import subtract\ndef test_subtract():\n    assert subtract(5, 3) == 2\n'
        )

        data = _run_with_inspect(
            pytester,
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-n',
            '2',
        )

        assert data['parallel_workers'] == 2

    def test_different_n_integer_sets_different_worker_count(self, pytester: pytest.Pytester) -> None:
        """-n 4 sets parallel_workers=4, ruling out any hardcoded worker count."""
        pytester.makepyfile(sample='def negate(x):\n    return -x\n')
        pytester.makepyfile(test_sample='from sample import negate\ndef test_negate():\n    assert negate(3) == -3\n')

        data = _run_with_inspect(
            pytester,
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-n',
            '4',
        )

        assert data['parallel_workers'] == 4

    def test_n_auto_sets_parallel_workers_to_positive_integer(self, pytester: pytest.Pytester) -> None:
        """-n auto sets parallel_workers to a positive integer (the resolved CPU count)."""
        pytester.makepyfile(sample='def add(a, b):\n    return a + b\n')
        pytester.makepyfile(test_sample='from sample import add\ndef test_add():\n    assert add(1, 2) == 3\n')

        data = _run_with_inspect(
            pytester,
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-n',
            'auto',
        )

        assert isinstance(data['parallel_workers'], int)
        assert data['parallel_workers'] > 0


@pytest.mark.medium
class TestDeprecationWarningForOldFlags:
    """Tests that --gremlin-parallel and --gremlin-workers warn when xdist is present."""

    def test_gremlin_parallel_warns_when_xdist_available(self, pytester_with_markers: pytest.Pytester) -> None:
        """--gremlin-parallel emits DeprecationWarning when xdist is installed."""
        pytester_with_markers.makepyfile(sample='def is_positive(x):\n    return x > 0\n')
        pytester_with_markers.makepyfile(
            test_sample='from sample import is_positive\ndef test_positive():\n    assert is_positive(5) is True\n'
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '-W',
            'always::DeprecationWarning',
            '-v',
        )

        result.stdout.fnmatch_lines(['*--gremlin-parallel*deprecated*'])

    def test_gremlin_workers_warns_when_xdist_available(self, pytester_with_markers: pytest.Pytester) -> None:
        """--gremlin-workers emits DeprecationWarning when xdist is installed."""
        pytester_with_markers.makepyfile(sample='def double(x):\n    return x * 2\n')
        pytester_with_markers.makepyfile(
            test_sample='from sample import double\ndef test_double():\n    assert double(4) == 8\n'
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-workers=2',
            '-W',
            'always::DeprecationWarning',
            '-v',
        )

        result.stdout.fnmatch_lines(['*--gremlin-parallel*deprecated*'])
