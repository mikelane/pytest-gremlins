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

from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.plugin import pytest_configure

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSET: object = object()  # sentinel: numprocesses attribute absent


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
    }
    if numprocesses is not _UNSET:
        attrs['numprocesses'] = numprocesses
    config = MagicMock()
    config.option = SimpleNamespace(**attrs)
    config.rootdir = '/fake/rootdir'
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

    def it_exits_zero_and_zaps_at_least_one_gremlin(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running --gremlins -n auto actually executes mutations and zaps at least one."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        result = pytester_with_markers.runpytest('--gremlins', '-n', 'auto', '-v')

        assert result.ret == 0, f'Expected exit code 0, got {result.ret}'
        output = result.stdout.str()
        assert 'Zapped:' in output, 'Expected at least one gremlin to be zapped — mutations did not run'

    def it_does_not_print_incompatibility_error(self, pytester_with_markers: pytest.Pytester) -> None:
        """Running --gremlins -n auto must not emit the old incompatibility message."""
        pytester_with_markers.makepyfile(target_module=_IS_ADULT_MODULE)
        pytester_with_markers.makepyfile(test_target=_IS_ADULT_TEST)

        result = pytester_with_markers.runpytest('--gremlins', '-n', 'auto', '-v')

        assert 'incompatible' not in result.stdout.str().lower()


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

        result = pytester_with_markers.runpytest('--gremlins', '-n', '2', '-v')

        assert result.ret == 0, f'Expected exit code 0, got {result.ret}'
        output = result.stdout.str()
        assert 'Zapped:' in output, 'Expected at least one gremlin to be zapped — mutations did not run'


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

        result = pytester_with_markers.runpytest('--gremlins', '-n', '4', '--gremlin-workers', '2', '-v')

        assert result.ret == 0, f'Expected exit code 0, got {result.ret}'
        output = result.stdout.str()
        assert 'Zapped:' in output, 'Expected at least one gremlin to be zapped — mutations did not run'


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

        result = pytester_with_markers.runpytest('--gremlins', '-n', '0', '-v')

        assert result.ret == 0, f'Expected exit code 0, got {result.ret}'
        output = result.stdout.str()
        assert 'Zapped:' in output, 'Expected at least one gremlin to be zapped — mutations did not run'


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

        result = pytester_with_markers.runpytest('-n', 'auto', '-v')

        assert result.ret == 0, f'Expected exit code 0, got {result.ret}'
        assert 'pytest-gremlins mutation report' not in result.stdout.str()


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

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            with (
                patch('pytest_gremlins.plugin.load_config'),
                patch('pytest_gremlins.plugin.merge_configs'),
                patch('pytest_gremlins.plugin.get_default_registry'),
                patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            ):
                pytest_configure(config)
            mock_pytest.exit.assert_not_called()

    def it_does_not_call_pytest_exit_with_gremlins_and_n_integer(self) -> None:
        """pytest_configure with gremlins=True, numprocesses=2 must not call pytest.exit."""
        config = _make_config(gremlins=True, numprocesses=2)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            with (
                patch('pytest_gremlins.plugin.load_config'),
                patch('pytest_gremlins.plugin.merge_configs'),
                patch('pytest_gremlins.plugin.get_default_registry'),
                patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            ):
                pytest_configure(config)
            mock_pytest.exit.assert_not_called()

    def it_does_not_call_pytest_exit_with_gremlins_and_n_zero(self) -> None:
        """pytest_configure with gremlins=True, numprocesses=0 must not call pytest.exit."""
        config = _make_config(gremlins=True, numprocesses=0)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            with (
                patch('pytest_gremlins.plugin.load_config'),
                patch('pytest_gremlins.plugin.merge_configs'),
                patch('pytest_gremlins.plugin.get_default_registry'),
                patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            ):
                pytest_configure(config)
            mock_pytest.exit.assert_not_called()
