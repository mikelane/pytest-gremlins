"""The cache key carries every rerun setting that can change a verdict, resolved the way the plugin reads it (#677)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.rerun_options import (
    rerun_cache_settings,
    rerun_ini_as_gremlin_runs_read,
)


def _option(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        'reruns_delay_backoff_factor': None,
        'only_rerun': None,
        'rerun_except': None,
        'rerun_exclude_path': None,
        'reruns_mode': 'strict',
        'max_suite_reruns': None,
    }
    return SimpleNamespace(**{**defaults, **overrides})


def _ini(**values: object) -> object:
    return values.get


@pytest.mark.small
class DescribeRerunCacheSettings:
    """Each forwarded setting beyond the count and delay changes the settings string."""

    @pytest.mark.parametrize(
        'changed',
        [
            {'reruns_delay_backoff_factor': 2.0},
            {'only_rerun': ['ConnectionError']},
            {'rerun_except': ['AssertionError']},
            {'rerun_exclude_path': ['tests/slow']},
            {'reruns_mode': 'append'},
            {'max_suite_reruns': 5},
        ],
    )
    def it_differs_from_the_defaults_when_one_option_is_set(self, changed: dict[str, object]) -> None:
        assert rerun_cache_settings(_option(**changed), _ini()) != rerun_cache_settings(_option(), _ini())

    @pytest.mark.parametrize('key', ['only_rerun', 'rerun_except'])
    def it_reads_a_filter_from_the_ini_key_like_the_cli_option(self, key: str) -> None:
        from_option = rerun_cache_settings(_option(**{key: ['Timeout']}), _ini())
        from_ini = rerun_cache_settings(_option(), _ini(**{key: ['Timeout']}))

        assert from_ini == from_option

    def it_reads_the_backoff_factor_from_the_ini_key_like_the_cli_option(self) -> None:
        from_option = rerun_cache_settings(_option(reruns_delay_backoff_factor=2.0), _ini())
        from_ini = rerun_cache_settings(_option(), _ini(reruns_delay_backoff_factor='2'))

        assert from_ini == from_option

    def it_prefers_the_option_over_the_ini_key(self) -> None:
        assert rerun_cache_settings(_option(only_rerun=['A']), _ini(only_rerun=['B'])) == rerun_cache_settings(
            _option(only_rerun=['A']), _ini()
        )

    def it_ignores_the_order_and_repeats_of_a_filter(self) -> None:
        assert rerun_cache_settings(_option(only_rerun=['B', 'A', 'B']), _ini()) == rerun_cache_settings(
            _option(only_rerun=['A', 'B']), _ini()
        )

    def it_keeps_two_filters_apart_when_their_items_swap(self) -> None:
        assert rerun_cache_settings(_option(only_rerun=['A'], rerun_except=['B']), _ini()) != rerun_cache_settings(
            _option(only_rerun=['B'], rerun_except=['A']), _ini()
        )

    def it_counts_a_negative_backoff_factor_as_none_like_the_plugin(self) -> None:
        assert rerun_cache_settings(_option(reruns_delay_backoff_factor=-3.0), _ini()) == rerun_cache_settings(
            _option(), _ini()
        )

    def it_reads_an_unreadable_ini_filter_as_unset(self) -> None:
        def unreadable(_key: str) -> object:
            raise ValueError

        assert rerun_cache_settings(_option(), unreadable) == rerun_cache_settings(_option(), _ini())


@pytest.mark.small
class DescribeRerunIniAsGremlinRunsRead:
    """A key reset for the gremlin runs reads as empty, so the cache key shows what they run with."""

    def it_reads_a_reset_key_as_empty(self) -> None:
        read = rerun_ini_as_gremlin_runs_read(_ini(rerun_except=['xyz ']), ['--override-ini=rerun_except='])

        assert read('rerun_except') == ''

    def it_reads_a_key_that_is_not_reset_unchanged(self) -> None:
        read = rerun_ini_as_gremlin_runs_read(_ini(only_rerun=['A']), ['--override-ini=rerun_except='])

        assert read('only_rerun') == ['A']

    def it_keys_a_reset_filter_like_an_unset_one(self) -> None:
        read = rerun_ini_as_gremlin_runs_read(_ini(rerun_except=['xyz ']), ['--override-ini=rerun_except='])

        assert rerun_cache_settings(_option(), read) == rerun_cache_settings(_option(), _ini())


@pytest.mark.medium
class DescribeRerunCacheSettingsThroughTheRealEntryPoint:
    """The session records the settings from the options pytest parsed."""

    @staticmethod
    def _recorded(pytester: pytest.Pytester, *args: str) -> str:
        pytester.makepyfile(sample='def one():\n    return 1\n')
        pytester.parseconfigure('--gremlins', '--gremlin-targets=sample.py', *args)
        session = plugin._get_session()
        assert session is not None
        return session.rerun_cache_settings

    def it_differs_between_runs_with_and_without_only_rerun(self, pytester: pytest.Pytester) -> None:
        filtered = self._recorded(pytester, '--only-rerun', 'ConnectionError')
        unfiltered = self._recorded(pytester)

        assert filtered != unfiltered

    def it_matches_between_the_command_line_flag_and_the_ini_key(self, pytester: pytest.Pytester) -> None:
        from_flag = self._recorded(pytester, '--only-rerun', 'ConnectionError')
        pytester.makeini('[pytest]\nonly_rerun = ConnectionError\n')
        from_ini = self._recorded(pytester)

        assert from_ini == from_flag

    def it_is_empty_when_pytest_rerunfailures_is_not_loaded(self, pytester: pytest.Pytester) -> None:
        pytester.makeini('[pytest]\nonly_rerun = ConnectionError\n')

        assert self._recorded(pytester, '-p', 'no:rerunfailures') == ''
