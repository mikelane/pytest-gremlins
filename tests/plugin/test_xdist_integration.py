"""BDD bootstrap for xdist coexistence — issue #295.

These tests define the DESIRED behavior of pytest-gremlins when used alongside
pytest-xdist (-n flag). They are expected to FAIL on the current codebase because
plugin.py:525 hard-errors (exit code 4) whenever --gremlins and -n are used together.

Tests will pass once the two-phase implementation (issue #296) is complete:
  Phase 1: xdist runs tests normally and collects coverage.
  Phase 2: gremlins runs mutations sequentially.

Scenarios:
  1. --gremlins -n auto succeeds with a mutation report.
  2. --gremlins -n 2 succeeds and shows a score percentage.
  3. --gremlins -n 4 --gremlin-workers 2 respects the worker override.
  4. --gremlins -n 0 is treated as no-parallelism (not an error).
  5. -n auto without --gremlins runs a plain pytest session unaffected.
  6. pytest_configure with gremlins=True, numprocesses=2 does NOT call pytest.exit.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import logging
from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

# Ensure xdist is present before any test in this module runs.
# Without this guard, pytester subprocesses receive '-n' but xdist is absent,
# causing CLI-parse errors that make negative assertions pass on broken code.
pytest.importorskip('xdist')

from pytest_gremlins.plugin import (
    GremlinSession,
    _set_session,
    pytest_configure,
    pytest_sessionfinish,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSET: object = object()  # sentinel: numprocesses attribute absent


@contextmanager
def _patch_configure_deps() -> Generator[MagicMock, None, None]:
    """Patch pytest_configure's external dependencies for unit testing.

    Yields the mock_pytest object so callers can assert on pytest.exit calls.
    Centralised here so that when pytest_configure gains new dependencies
    during issue #296 implementation, only this one block needs updating.
    """
    with (
        patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        patch('pytest_gremlins.plugin.load_config'),
        patch('pytest_gremlins.plugin.merge_configs'),
        patch('pytest_gremlins.plugin.get_default_registry'),
        patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
    ):
        yield mock_pytest


def _make_config(
    *,
    gremlins: bool = False,
    gremlin_parallel: bool = False,
    gremlin_workers: int | None = None,
    gremlin_operators: str | None = None,
    gremlin_targets: str | None = None,
    gremlin_report: str = 'console',
    gremlin_cache: bool = False,
    gremlin_clear_cache: bool = False,
    gremlin_batch: bool = False,
    gremlin_batch_size: int = 10,
    numprocesses: object = _UNSET,
) -> MagicMock:
    """Build a mock pytest.Config with the given option values.

    Args:
        gremlins: Whether --gremlins flag is active.
        gremlin_parallel: Whether --gremlin-parallel flag is active.
        gremlin_workers: Value of --gremlin-workers (None = unset).
        gremlin_operators: Operator filter string.
        gremlin_targets: Target module filter string.
        gremlin_report: Report format ('console' default).
        gremlin_cache: Whether --gremlin-cache is active.
        gremlin_clear_cache: Whether --gremlin-clear-cache is active.
        gremlin_batch: Whether --gremlin-batch is active.
        gremlin_batch_size: Batch size for gremlin runs.
        numprocesses: xdist -n value. Pass _UNSET to simulate xdist not installed,
            None to simulate xdist installed but -n not passed, 'auto' or int for -n N.
    """
    attrs: dict[str, object] = {
        'gremlins': gremlins,
        'gremlin_parallel': gremlin_parallel,
        'gremlin_workers': gremlin_workers,
        'gremlin_operators': gremlin_operators,
        'gremlin_targets': gremlin_targets,
        'gremlin_report': gremlin_report,
        'gremlin_cache': gremlin_cache,
        'gremlin_clear_cache': gremlin_clear_cache,
        'gremlin_batch': gremlin_batch,
        'gremlin_batch_size': gremlin_batch_size,
        'strict_pardons': False,
        'gremlin_audit_pardons': False,
        'gremlin_max_pardons_pct': None,
        'max_pardons': None,
        'gremlin_exclude': None,
    }
    if numprocesses is not _UNSET:
        attrs['numprocesses'] = numprocesses
    # spec=pytest.Config is intentionally omitted: pytest.Config sets `option`
    # dynamically in __init__, so MagicMock(spec=pytest.Config) would raise
    # AttributeError on config.option. Instead we explicitly configure every
    # attribute that production code reads, which achieves the same drift-detection
    # goal without the spec= footgun.
    config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
    config.option = SimpleNamespace(**attrs)
    config.rootdir = '/fake/rootdir'
    # Prevent _detect_coverage_mode from seeing a truthy auto-mock for the
    # coverage plugin. MagicMock auto-creates attributes, so without this line
    # get_plugin('_cov') returns MagicMock() (truthy) instead of None, causing
    # _detect_coverage_mode to return CoverageMode.PIGGYBACK silently.
    config.pluginmanager.get_plugin.return_value = None
    return config


# ---------------------------------------------------------------------------
# Pytester fixtures shared across classes
# ---------------------------------------------------------------------------

_IS_ADULT_MODULE = """
def is_adult(age):
    return age >= 18
"""

_IS_ADULT_TEST = """
from target_module import is_adult

def test_is_adult_true_for_21():
    assert is_adult(21) is True

def test_is_adult_false_for_10():
    assert is_adult(10) is False

def test_boundary():
    # Kills the >= to > mutation: is_adult(18) returns False under mutation
    assert is_adult(18) is True
"""


# ---------------------------------------------------------------------------
# Scenario 1 — two-phase run with -n auto
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribeXdistCoexistenceWithNAuto:
    """pytest-gremlins succeeds when invoked with --gremlins and -n auto.

    Current behavior: exits with code 4 (hard error in plugin.py:525).
    Expected behavior after issue #296: exits 0, mutation report in stdout.
    """

    def it_exits_zero_zaps_at_least_one_gremlin_and_omits_incompatibility_error(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        """Running --gremlins -n auto executes mutations, exits 0, and emits no incompatibility message."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        pytest_run_result = pytester_with_markers.runpytest('--gremlins', '-n', 'auto', '-v')

        assert pytest_run_result.ret == 0, f'Expected exit code 0, got {pytest_run_result.ret}'
        stdout = pytest_run_result.stdout.str()
        # 'Zapped:' proves mutations actually ran — exit 0 with no mutations would pass
        # the exit-code check but deliver nothing, defeating the purpose of the feature.
        assert 'Zapped:' in stdout, 'Expected at least one gremlin to be zapped — mutations did not run'
        # 'incompatible' absence proves the old guard at plugin.py:525 was removed,
        # not merely suppressed while still blocking mutation execution.
        assert 'incompatible' not in stdout.lower()


# ---------------------------------------------------------------------------
# Scenario 2 — worker count from -n integer
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribeXdistCoexistenceWithNInteger:
    """pytest-gremlins succeeds when invoked with --gremlins and -n 2.

    Current behavior: exits with code 4.
    Expected behavior after issue #296: exits 0, score percentage in stdout.
    """

    def it_exits_zero_and_zaps_at_least_one_gremlin(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running --gremlins -n 2 actually executes mutations and zaps at least one."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        pytest_run_result = pytester_with_markers.runpytest('--gremlins', '-n', '2', '-v')

        assert pytest_run_result.ret == 0, f'Expected exit code 0, got {pytest_run_result.ret}'
        stdout = pytest_run_result.stdout.str()
        assert 'Zapped:' in stdout, 'Expected at least one gremlin to be zapped — mutations did not run'


# ---------------------------------------------------------------------------
# Scenario 3 — --gremlin-workers overrides -n count
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribeGremlinWorkersOverridesN:
    """--gremlin-workers takes precedence over -n for the mutation phase.

    Current behavior: exits with code 4.
    Expected behavior after issue #296: exits 0, mutation report in stdout.
    """

    def it_exits_zero_and_zaps_at_least_one_gremlin(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running --gremlins -n 4 --gremlin-workers 2 actually executes mutations and zaps at least one."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        pytest_run_result = pytester_with_markers.runpytest('--gremlins', '-n', '4', '--gremlin-workers', '2', '-v')

        assert pytest_run_result.ret == 0, f'Expected exit code 0, got {pytest_run_result.ret}'
        stdout = pytest_run_result.stdout.str()
        assert 'Zapped:' in stdout, 'Expected at least one gremlin to be zapped — mutations did not run'


# ---------------------------------------------------------------------------
# Scenario 4 — -n 0 treated as no parallelism (not an error)
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribeXdistNZeroIsNotAnError:
    """--gremlins -n 0 treats xdist as disabled and runs normally.

    xdist interprets -n 0 as "no distributed testing". Gremlins must do the same.

    Current behavior: exits with code 4 (the existing guard fires on any non-None numprocesses).
    Expected behavior after issue #296: exits 0, mutation report in stdout.
    """

    def it_exits_zero_and_zaps_at_least_one_gremlin(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running --gremlins -n 0 actually executes mutations and zaps at least one."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        pytest_run_result = pytester_with_markers.runpytest('--gremlins', '-n', '0', '-v')

        assert pytest_run_result.ret == 0, f'Expected exit code 0, got {pytest_run_result.ret}'
        stdout = pytest_run_result.stdout.str()
        assert 'Zapped:' in stdout, 'Expected at least one gremlin to be zapped — mutations did not run'


# ---------------------------------------------------------------------------
# Scenario 5 — -n without --gremlins runs unaffected (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribeXdistAloneIsUnaffected:
    """Running pytest with -n but without --gremlins is a plain distributed run.

    This is a regression guard: the two-phase implementation must not break
    normal xdist-only usage.

    Current behavior: already passes (no conflict). Must stay passing.
    """

    def it_runs_normally_without_mutation_report(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running -n auto without --gremlins produces no mutation report."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        pytest_run_result = pytester_with_markers.runpytest('-n', 'auto', '-v')

        # Positive assertion first: all 3 tests must have actually run and passed.
        # Without this, a silent plugin crash that exits 0 with no output would
        # satisfy the two negative assertions below, giving a false green.
        pytest_run_result.assert_outcomes(passed=3)
        assert pytest_run_result.ret == 0, f'Expected exit code 0, got {pytest_run_result.ret}'
        assert 'pytest-gremlins mutation report' not in pytest_run_result.stdout.str()


# ---------------------------------------------------------------------------
# Scenario 6 — pytest_configure does NOT call pytest.exit when gremlins+n>=1 (unit)
# ---------------------------------------------------------------------------


@pytest.mark.medium
@pytest.mark.xdist_integration
class DescribePytestConfigureDoesNotExitWithXdist:
    """pytest_configure does not call pytest.exit when --gremlins and -n are combined.

    This unit-level check verifies the removal of the incompatibility guard.

    Current behavior: pytest.exit IS called (the guard at plugin.py:525 fires).
    Expected behavior after issue #296: pytest.exit is NOT called.
    """

    def it_does_not_call_pytest_exit_with_gremlins_and_n_auto(self) -> None:
        """pytest_configure with gremlins=True, numprocesses='auto' must not call pytest.exit."""
        config = _make_config(gremlins=True, numprocesses='auto')

        with _patch_configure_deps() as mock_pytest:
            pytest_configure(config)
        mock_pytest.exit.assert_not_called()

    def it_does_not_call_pytest_exit_with_gremlins_and_n_integer(self) -> None:
        """pytest_configure with gremlins=True, numprocesses=2 must not call pytest.exit."""
        config = _make_config(gremlins=True, numprocesses=2)

        with _patch_configure_deps() as mock_pytest:
            pytest_configure(config)
        mock_pytest.exit.assert_not_called()

    def it_does_not_call_pytest_exit_with_gremlins_and_n_zero(self) -> None:
        """pytest_configure with gremlins=True, numprocesses=0 must not call pytest.exit."""
        config = _make_config(gremlins=True, numprocesses=0)

        with _patch_configure_deps() as mock_pytest:
            pytest_configure(config)
        mock_pytest.exit.assert_not_called()

    def it_calls_pytest_exit_when_max_pardons_is_negative(self) -> None:
        """pytest_configure with max_pardons=-1 calls pytest.exit regardless of xdist state."""
        config = _make_config(gremlins=True, numprocesses=2)
        config.option.max_pardons = -1

        with _patch_configure_deps() as mock_pytest:
            pytest_configure(config)
        mock_pytest.exit.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 7 — pytest_sessionfinish sets total_tests from xdist_item_ids
# ---------------------------------------------------------------------------


@pytest.mark.small
class DescribeSessionFinishSetsTotalTestsInXdistMode:
    """pytest_sessionfinish sets total_tests from xdist_item_ids in xdist two-phase mode.

    In xdist mode the controller collects no items, so pytest_collection_finish
    sets total_tests=0. pytest_sessionfinish must correct this from xdist_item_ids
    so that progress output shows 'running N/M' not 'running N/0'.
    """

    def it_sets_total_tests_to_the_count_of_normalized_xdist_item_ids(self) -> None:
        """total_tests is updated to len(normalized xdist_item_ids) before mutation runs."""
        gs = GremlinSession(
            enabled=True,
            xdist_active=True,
            xdist_item_ids=['tests/test_m.py::test_a', 'tests/test_m.py::test_b', 'tests/test_m.py::test_c'],
            total_tests=0,
        )
        _set_session(gs)

        mock_session = MagicMock(spec=pytest.Session)
        mock_session.config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        mock_session.config.rootdir = '/fake/root'
        mock_session.config.workerinput = MagicMock(side_effect=AttributeError)  # simulates missing attr; bare-mock: ok

        with (
            patch('pytest_gremlins.plugin._is_xdist_worker', return_value=False),
            patch(
                'pytest_gremlins.plugin._get_rootdir',
                return_value=MagicMock(__str__=lambda _: '/fake/root'),  # bare-mock: ok
            ),
            patch('pytest_gremlins.plugin._make_node_ids_relative', return_value=['test_a', 'test_b', 'test_c']),
            patch('pytest_gremlins.plugin._discover_source_files', return_value={}),
            patch('pytest_gremlins.plugin._generate_gremlins'),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)

        assert gs.total_tests == 3

    def it_logs_warning_when_no_xdist_item_ids_are_available(self, caplog: pytest.LogCaptureFixture) -> None:
        """When xdist_item_ids is None, pytest_sessionfinish logs a warning and proceeds."""
        gs = GremlinSession(enabled=True, xdist_active=True, xdist_item_ids=None)
        _set_session(gs)

        mock_session = MagicMock(spec=pytest.Session)
        mock_session.config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        mock_session.config.workerinput = MagicMock(side_effect=AttributeError)  # simulates missing attr; bare-mock: ok

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.plugin'),
            patch('pytest_gremlins.plugin._is_xdist_worker', return_value=False),
            patch(
                'pytest_gremlins.plugin._get_rootdir',
                return_value=MagicMock(__str__=lambda _: '/fake/root'),  # bare-mock: ok
            ),
            patch('pytest_gremlins.plugin._make_node_ids_relative', return_value=[]),
            patch('pytest_gremlins.plugin._discover_source_files', return_value={}),
            patch('pytest_gremlins.plugin._generate_gremlins'),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)

        assert any('pytest_xdist_node_collection_finished may not have fired' in r.message for r in caplog.records)
