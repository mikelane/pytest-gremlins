"""The per-mutant timeout grows with the rerun budget pytest-rerunfailures gives each test (issue #655)."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.config import MAX_TIMEOUT_SECONDS
from pytest_gremlins.rerun_options import (
    scaled_mutant_timeout,
    session_rerun_backoff_factor,
    session_rerun_budget,
)


@pytest.mark.small
class DescribeScaledMutantTimeout:
    @pytest.mark.parametrize('reruns', [0, -1])
    def it_returns_the_base_timeout_when_there_are_no_reruns(self, reruns: int) -> None:
        assert scaled_mutant_timeout(30, reruns=reruns, reruns_delay=20) == 30

    @pytest.mark.parametrize(
        ('base', 'reruns', 'delay', 'expected'),
        [
            (30, 1, 0, 60),
            (30, 2, 0, 90),
            (30, 2, 20, 130),
            (10, 3, 1, 43),
        ],
    )
    def it_allows_every_attempt_its_full_budget_plus_the_delays(
        self, base: int, reruns: int, delay: float, expected: int
    ) -> None:
        assert scaled_mutant_timeout(base, reruns=reruns, reruns_delay=delay) == expected

    @pytest.mark.parametrize(('delay', 'expected'), [(0.1, 61), (0.5, 61), (1.5, 62)])
    def it_rounds_the_total_delay_up_to_whole_seconds(self, delay: float, expected: int) -> None:
        assert scaled_mutant_timeout(30, reruns=1, reruns_delay=delay) == expected

    def it_rounds_the_summed_delay_not_each_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=4, reruns_delay=0.5) == 152

    @pytest.mark.parametrize('delay', [-5, -0.5])
    def it_treats_a_negative_delay_as_no_delay(self, delay: float) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=delay) == 90

    def it_never_exceeds_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(MAX_TIMEOUT_SECONDS, reruns=5, reruns_delay=100) == MAX_TIMEOUT_SECONDS

    def it_clamps_an_infinite_delay_to_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('inf')) == MAX_TIMEOUT_SECONDS

    @pytest.mark.parametrize('delay', [0, 0.5, 20])
    def it_clamps_a_rerun_count_too_large_for_a_float_to_the_maximum_timeout(self, delay: float) -> None:
        assert scaled_mutant_timeout(30, reruns=10**400, reruns_delay=delay) == MAX_TIMEOUT_SECONDS

    def it_treats_a_delay_that_is_not_a_number_as_no_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('nan')) == 90

    def it_adds_the_geometric_sum_of_the_backed_off_delays(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=1, reruns_delay_backoff_factor=3) == 94

    @pytest.mark.parametrize(
        ('reruns', 'factor', 'expected'),
        [
            (3, 2, 30 * 4 + 7),
            (3, 0.5, 30 * 4 + 2),
            (3, 0, 30 * 4 + 1),
            (1, 10, 30 * 2 + 1),
        ],
    )
    def it_sums_delay_times_factor_to_the_attempt_for_each_rerun(
        self, reruns: int, factor: float, expected: int
    ) -> None:
        assert scaled_mutant_timeout(30, reruns=reruns, reruns_delay=1, reruns_delay_backoff_factor=factor) == expected

    def it_does_not_round_down_a_factor_just_above_one(self) -> None:
        # The exact sum is 50000.000125 seconds; a closed-form (f**n - 1) / (f - 1) cancels to 50000.0.
        assert (
            scaled_mutant_timeout(1, reruns=5000, reruns_delay=10, reruns_delay_backoff_factor=1 + 1e-12)
            == 5001 + 50001
        )

    def it_behaves_as_a_constant_delay_when_the_factor_is_one(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=20, reruns_delay_backoff_factor=1.0) == 130

    def it_adds_no_delay_when_the_delay_is_zero_whatever_the_factor(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=0, reruns_delay_backoff_factor=1000) == 90

    def it_clamps_a_backoff_that_overflows_a_float_to_the_maximum_timeout(self) -> None:
        assert (
            scaled_mutant_timeout(30, reruns=5000, reruns_delay=1, reruns_delay_backoff_factor=10)
            == MAX_TIMEOUT_SECONDS
        )

    def it_clamps_an_infinite_factor_to_the_maximum_timeout(self) -> None:
        factor = float('inf')

        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=1, reruns_delay_backoff_factor=factor) == (
            MAX_TIMEOUT_SECONDS
        )

    def it_clamps_an_infinite_delay_with_a_zero_factor_to_the_maximum_timeout(self) -> None:
        assert (
            scaled_mutant_timeout(30, reruns=3, reruns_delay=float('inf'), reruns_delay_backoff_factor=0)
            == MAX_TIMEOUT_SECONDS
        )

    @pytest.mark.parametrize('factor', [-1, -0.5, float('nan')])
    def it_treats_a_factor_pytest_rerunfailures_rejects_as_a_constant_delay(self, factor: float) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=20, reruns_delay_backoff_factor=factor) == 130

    def it_ignores_the_factor_when_there_are_no_reruns(self) -> None:
        assert scaled_mutant_timeout(30, reruns=0, reruns_delay=20, reruns_delay_backoff_factor=5) == 30


def _unregistered_ini_key(key: str) -> object:
    # config.getini raises ValueError for a key no loaded plugin registers.
    raise ValueError(f'unknown configuration value: {key!r}')


@pytest.mark.small
class DescribeSessionRerunBudget:
    def it_counts_an_ini_key_the_installed_plugin_does_not_register_as_no_reruns(self) -> None:
        option = SimpleNamespace(reruns=None, reruns_delay=None)

        assert session_rerun_budget(option, _unregistered_ini_key) == (0, 0.0)

    def it_reads_the_ini_file_when_the_options_are_not_registered_at_all(self) -> None:
        ini = {'reruns': '2', 'reruns_delay': '1.5'}

        assert session_rerun_budget(SimpleNamespace(), ini.get) == (2, 1.5)

    def it_falls_back_to_the_reruns_option_when_force_reruns_is_unset(self) -> None:
        option = SimpleNamespace(force_reruns=None, reruns=1, reruns_delay=None)

        assert session_rerun_budget(option, {'reruns': '5'}.get) == (1, 0.0)


@pytest.mark.small
class DescribeSessionRerunBackoffFactor:
    def it_defaults_to_one_when_nothing_sets_it(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=None)

        assert session_rerun_backoff_factor(option, {}.get) == 1.0

    def it_reads_the_command_line_option(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=2.5)

        assert session_rerun_backoff_factor(option, {'reruns_delay_backoff_factor': '9'}.get) == 2.5

    def it_reads_the_ini_key_when_the_option_is_unset(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=None)

        assert session_rerun_backoff_factor(option, {'reruns_delay_backoff_factor': '3'}.get) == 3.0

    def it_reads_the_ini_key_when_the_option_is_not_registered_at_all(self) -> None:
        assert session_rerun_backoff_factor(SimpleNamespace(), {'reruns_delay_backoff_factor': '3'}.get) == 3.0

    def it_counts_an_ini_value_that_is_not_a_number_as_one(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=None)

        assert session_rerun_backoff_factor(option, {'reruns_delay_backoff_factor': 'fast'}.get) == 1.0

    def it_counts_an_ini_key_the_installed_plugin_does_not_register_as_one(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=None)

        assert session_rerun_backoff_factor(option, _unregistered_ini_key) == 1.0

    def it_counts_a_negative_factor_as_one_the_way_the_plugin_does(self) -> None:
        option = SimpleNamespace(reruns_delay_backoff_factor=-2.0)

        assert session_rerun_backoff_factor(option, {}.get) == 1.0


@pytest.mark.small
class DescribeRerunScaledMutantTimeoutLog:
    def it_logs_the_scaled_timeout_at_debug_level(self, caplog: pytest.LogCaptureFixture) -> None:
        config = SimpleNamespace(
            option=SimpleNamespace(force_reruns=None, reruns=2, reruns_delay=20.0),
            getini=lambda _key: None,
            pluginmanager=SimpleNamespace(hasplugin=lambda _name: True),
        )

        with caplog.at_level(logging.DEBUG, logger=plugin.logger.name):
            plugin._rerun_scaled_timeout(config, 30, label='Mutant')

        assert '-> 130s' in caplog.text

    def it_logs_the_backoff_factor(self, caplog: pytest.LogCaptureFixture) -> None:
        config = SimpleNamespace(
            option=SimpleNamespace(force_reruns=None, reruns=2, reruns_delay=1.0, reruns_delay_backoff_factor=3.0),
            getini=lambda _key: None,
            pluginmanager=SimpleNamespace(hasplugin=lambda _name: True),
        )

        with caplog.at_level(logging.DEBUG, logger=plugin.logger.name):
            plugin._rerun_scaled_timeout(config, 30, label='Mutant')

        assert 'backoff_factor=3.0' in caplog.text
        assert '-> 94s' in caplog.text


def _configured_session(pytester: pytest.Pytester, *args: str, ini: str = '') -> plugin.GremlinSession:
    pytester.makepyfile(sample='def one():\n    return 1\n')
    pytester.makeini(f'[pytest]\n{ini}\n')
    pytester.parseconfigure('--gremlins', '--gremlin-targets=sample.py', *args)
    session = plugin._get_session()
    assert session is not None
    assert session.enabled
    return session


def _configured_mutant_timeout(pytester: pytest.Pytester, *args: str, ini: str = '') -> int:
    return _configured_session(pytester, *args, ini=ini).mutant_timeout


def _configured_coverage_timeout(pytester: pytest.Pytester, *args: str, ini: str = '') -> int:
    return _configured_session(pytester, *args, ini=ini).coverage_timeout


@pytest.mark.medium
class DescribeMutantTimeoutThroughTheRealEntryPoint:
    def it_scales_the_default_timeout_by_the_command_line_reruns(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '2', '--reruns-delay', '20') == 130

    def it_scales_an_explicit_timeout_too(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(pytester, '--gremlin-mutant-timeout', '5', '--reruns', '1')

        assert timeout == 10

    def it_scales_by_the_reruns_in_the_ini_file(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, ini='reruns = 2\nreruns_delay = 1.5') == 93

    def it_prefers_the_command_line_count_over_the_ini_count(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '1', ini='reruns = 5') == 60

    def it_takes_the_delay_from_the_ini_file_when_only_the_count_is_on_the_command_line(
        self, pytester: pytest.Pytester
    ) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '1', ini='reruns_delay = 9') == 69

    def it_prefers_the_command_line_delay_over_the_ini_delay(self, pytester: pytest.Pytester) -> None:
        assert (
            _configured_mutant_timeout(pytester, '--reruns', '1', '--reruns-delay', '2', ini='reruns_delay = 9') == 62
        )

    def it_lets_force_reruns_set_the_rerun_count(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--force-reruns', '3', '--reruns', '1') == 120

    def it_adds_the_backed_off_delays_from_the_command_line(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(
            pytester, '--reruns', '2', '--reruns-delay', '1', '--reruns-delay-backoff-factor', '3'
        )

        assert timeout == 94

    def it_adds_the_backed_off_delays_from_the_ini_file(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(
            pytester, ini='reruns = 2\nreruns_delay = 1\nreruns_delay_backoff_factor = 3'
        )

        assert timeout == 94

    def it_prefers_the_command_line_factor_over_the_ini_factor(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(
            pytester,
            '--reruns',
            '2',
            '--reruns-delay',
            '1',
            '--reruns-delay-backoff-factor',
            '2',
            ini='reruns_delay_backoff_factor = 9',
        )

        assert timeout == 93

    def it_leaves_the_timeout_alone_when_reruns_is_zero(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '0', '--reruns-delay', '20') == 30

    def it_leaves_the_timeout_alone_when_no_reruns_are_configured(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester) == 30

    def it_ignores_a_value_that_is_not_a_number_in_the_ini_file(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, ini='reruns = lots') == 30

    def it_leaves_the_timeout_alone_when_pytest_rerunfailures_is_not_loaded(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(pytester, '-p', 'no:rerunfailures', ini='reruns = 2')

        assert timeout == 30


@pytest.mark.medium
class DescribeCoverageTimeoutThroughTheRealEntryPoint:
    def it_scales_the_default_pre_scan_timeout_by_the_command_line_reruns(self, pytester: pytest.Pytester) -> None:
        assert _configured_coverage_timeout(pytester, '--reruns', '2', '--reruns-delay', '20') == 400

    def it_scales_an_explicit_pre_scan_timeout_too(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_coverage_timeout(pytester, '--gremlin-coverage-timeout', '5', '--reruns', '1')

        assert timeout == 10

    def it_scales_by_the_reruns_in_the_ini_file(self, pytester: pytest.Pytester) -> None:
        assert _configured_coverage_timeout(pytester, ini='reruns = 1\nreruns_delay = 3') == 243

    def it_leaves_the_pre_scan_timeout_alone_when_no_reruns_are_configured(self, pytester: pytest.Pytester) -> None:
        assert _configured_coverage_timeout(pytester) == 120

    def it_leaves_the_pre_scan_timeout_alone_when_pytest_rerunfailures_is_not_loaded(
        self, pytester: pytest.Pytester
    ) -> None:
        assert _configured_coverage_timeout(pytester, '-p', 'no:rerunfailures', ini='reruns = 2') == 120

    def it_records_the_per_attempt_pre_scan_timeout(self, pytester: pytest.Pytester) -> None:
        session = _configured_session(pytester, '--gremlin-coverage-timeout', '5', '--reruns', '1')

        assert session.coverage_attempt_timeout == 5

    def it_records_the_per_attempt_mutant_timeout(self, pytester: pytest.Pytester) -> None:
        session = _configured_session(pytester, '--gremlin-mutant-timeout', '7', '--reruns', '1')

        assert session.mutant_attempt_timeout == 7


_ADDITION = """
def add(a, b):
    return a + b
"""

_TEST_THAT_KILLS_THE_MUTANT = """
import pytest
from sample import add


@pytest.mark.medium
def test_add():
    assert add(2, 3) == 5
"""

# The mutant's covering test fails, is rerun after the delay, and fails again.  The delay alone is longer than the
# limit of one attempt, so only a timeout widened by the rerun budget lets that kill finish as a kill.  The pytest
# start-up of the two attempts (up to 7s each on a loaded runner) fits in the scaled limit with room to spare.
_ONE_ATTEMPT_LIMIT = 10
_RERUN_DELAY = 12


@pytest.mark.medium
class DescribeRerunDelayEndToEnd:
    def it_zaps_a_mutant_whose_covering_test_waits_out_a_rerun_delay(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester.makepyfile(sample=_ADDITION, test_sample=_TEST_THAT_KILLS_THE_MUTANT)

        result = pytester.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            '--gremlin-mutant-timeout',
            str(_ONE_ATTEMPT_LIMIT),
            '--reruns',
            '1',
            '--reruns-delay',
            str(_RERUN_DELAY),
            '-p',
            'no:cacheprovider',
        )

        output = result.stdout.str()
        assert re.search(r'Zapped: [1-9]\d* gremlins', output), output
        assert 'Timeout:' not in output, output
        assert 'Error:' not in output, output
