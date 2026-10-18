"""Rerun options typed on the command line are carried into gremlin runs (refs #546)."""

from __future__ import annotations

from collections.abc import (
    Callable,
    Mapping,
)
from types import SimpleNamespace

import pytest

from pytest_gremlins.rerun_options import (
    baseline_rerun_warning,
    rerun_ini_overrides,
    rerun_keys_set_in,
    rerun_options_in,
    rerun_resets,
    survives_override_ini,
    unforwardable_rerun_keys,
    unforwarded_rerun_key_warning,
)


@pytest.mark.small
class DescribeRerunOptionsIn:
    @pytest.mark.parametrize(
        ('args', 'expected'),
        [
            (['--reruns', '2'], ['--reruns=2']),
            (['--reruns=2'], ['--reruns=2']),
            (['--reruns', '3', '--reruns-delay', '0.5'], ['--reruns=3', '--reruns-delay=0.5']),
            (['--only-rerun', 'Timeout', '--only-rerun=Conn.*'], ['--only-rerun=Timeout', '--only-rerun=Conn.*']),
            (['--rerun-except', 'AssertionError'], ['--rerun-except=AssertionError']),
            (['--rerun-exclude-path', 'tests/slow'], ['--rerun-exclude-path=tests/slow']),
            (['--reruns-mode', 'append'], ['--reruns-mode=append']),
            (['--reruns-delay-backoff-factor=2'], ['--reruns-delay-backoff-factor=2']),
            (['--force-reruns', '1'], ['--force-reruns=1']),
            (['--max-suite-reruns', '10'], ['--max-suite-reruns=10']),
        ],
    )
    def it_keeps_each_rerun_option_with_its_value(self, args: list[str], expected: list[str]) -> None:
        assert rerun_options_in(args) == expected

    @pytest.mark.parametrize(
        'args',
        [
            ['-o', 'reruns=2'],
            ['-o=reruns=2'],
            ['-oreruns=2'],
            ['--override-ini', 'reruns=2'],
            ['--override-ini=reruns=2'],
        ],
    )
    def it_keeps_the_rerun_ini_settings_overridden_on_the_command_line(self, args: list[str]) -> None:
        assert rerun_options_in(args) == ['--override-ini=reruns=2']

    @pytest.mark.parametrize(
        'setting', ['only_rerun=ConnectionError', 'rerun_except=AssertionError', 'reruns_delay_backoff_factor=2']
    )
    def it_carries_every_ini_key_pytest_rerunfailures_reads(self, setting: str) -> None:
        assert rerun_options_in(['-o', setting]) == [f'--override-ini={setting}']

    def it_carries_an_ini_override_written_after_a_short_flag(self) -> None:
        # argparse reads ``-qo reruns=2`` as ``-q -o reruns=2``.
        assert rerun_options_in(['-qo', 'reruns=2']) == ['--override-ini=reruns=2']

    def it_carries_an_ini_override_written_as_a_clustered_flag_with_an_equals_sign(self) -> None:
        # argparse reads ``-qo=reruns=2`` as ``-q -o reruns=2``, just as it reads ``-o=reruns=2`` as ``-o reruns=2``.
        assert rerun_options_in(['-qo=reruns=2']) == ['--override-ini=reruns=2']

    def it_keeps_the_rerun_delay_ini_override_and_drops_unrelated_ones(self) -> None:
        args = ['-o', 'log_level=DEBUG', '-o', 'reruns_delay=0.5', '-o', 'rerunsx=1']

        assert rerun_options_in(args) == ['--override-ini=reruns_delay=0.5']

    def it_does_not_take_a_trailing_override_ini_option_as_a_rerun_setting(self) -> None:
        assert rerun_options_in(['-o']) == []

    def it_does_not_read_an_o_clustered_after_a_flag_that_takes_a_value_as_an_ini_override(self) -> None:
        # argparse reads ``-ko reruns=2`` as ``-k o`` followed by the positional ``reruns=2``.
        assert rerun_options_in(['-ko', 'reruns=2']) == []

    def it_ignores_every_other_argument(self) -> None:
        args = ['tests/', '-x', '--reruns', '2', '-k', 'flaky', '--gremlins', '-n', '2']

        assert rerun_options_in(args) == ['--reruns=2']

    @pytest.mark.parametrize('flag', ['--fail-on-flaky', '--rerun-show-tracebacks'])
    def it_leaves_out_options_that_change_the_exit_code_or_only_the_output(self, flag: str) -> None:
        assert rerun_options_in([flag, '--reruns', '1']) == ['--reruns=1']

    def it_does_not_take_the_next_argument_as_the_value_of_a_trailing_option(self) -> None:
        assert rerun_options_in(['--reruns']) == []

    def it_returns_nothing_when_no_rerun_option_was_typed(self) -> None:
        assert rerun_options_in(['--gremlins', 'tests/']) == []


@pytest.mark.small
class DescribeBaselineRerunWarning:
    def it_returns_nothing_when_no_test_needed_a_rerun(self) -> None:
        assert baseline_rerun_warning(set()) is None

    def it_names_the_test_that_needed_a_rerun(self) -> None:
        warning = baseline_rerun_warning({'tests/test_a.py::test_flaky'})

        assert warning is not None
        assert 'tests/test_a.py::test_flaky' in warning
        assert warning.startswith('pytest-gremlins: warning:')

    def it_is_a_single_line_naming_every_test_in_sorted_order(self) -> None:
        warning = baseline_rerun_warning({'t::b', 't::a'})

        assert warning is not None
        assert '\n' not in warning
        assert warning.index('t::a') < warning.index('t::b')

    def it_summarizes_the_tests_beyond_the_first_ten(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(13)})

        assert warning is not None
        assert 't::test_09' in warning
        assert 't::test_10' not in warning
        assert 'and 3 more' in warning

    def it_names_exactly_ten_tests_without_a_summary(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(10)})

        assert warning is not None
        assert 't::test_09' in warning
        assert 'more' not in warning

    def it_states_how_many_baseline_tests_needed_a_rerun(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(13)})

        assert warning is not None
        assert '13 baseline test(s) needed a rerun' in warning


@pytest.mark.small
class DescribeSurvivesOverrideIni:
    @pytest.mark.parametrize(
        'items',
        [[], ['Timeout'], ['bad gateway', 'AssertionError'], ['a\tb'], ['trailing\\']],
    )
    def it_accepts_items_pytest_reads_back_unchanged(self, items: list[str]) -> None:
        assert survives_override_ini(items) is True

    @pytest.mark.parametrize(
        'items',
        [
            ['xyz '],
            [' xyz'],
            ['a', 'b '],
            ['a\nb'],
            ['a\rb'],
            ['a\r'],
            [''],
            ['a', ''],
            ['\t'],
            ['a\u00a0'],
            ['a\x00b'],
        ],
        ids=[
            'trailing',
            'leading',
            'second-item',
            'newline',
            'carriage-return',
            'trailing-cr',
            'empty',
            'empty-second',
            'tab',
            'nbsp',
            'null-byte',
        ],
    )
    def it_rejects_items_pytest_would_strip_split_or_drop(self, items: list[str]) -> None:
        assert survives_override_ini(items) is False


def _ini_reader(values: dict[str, str | list[str]]) -> Callable[[str], object]:
    """Return a ``config.getini`` stand-in that reads an unset list key as ``[]`` and any other as ``''``."""
    return lambda key: values.get(key, [] if key in ('only_rerun', 'rerun_except') else '')


@pytest.mark.small
class DescribeUnforwardableRerunKeys:
    _reader = staticmethod(_ini_reader)

    def it_names_each_list_key_with_an_item_pytest_would_change(self) -> None:
        values: dict[str, str | list[str]] = {'reruns': '2', 'only_rerun': ['a '], 'rerun_except': ['b ']}

        assert unforwardable_rerun_keys(self._reader(values)) == ['only_rerun', 'rerun_except']

    def it_names_nothing_when_every_item_survives(self) -> None:
        assert unforwardable_rerun_keys(self._reader({'rerun_except': ['a b']})) == []

    def it_skips_a_key_the_command_line_overrides(self) -> None:
        values: dict[str, str | list[str]] = {'rerun_except': ['a ']}

        overridden_by = ['--override-ini=rerun_except=a']

        assert unforwardable_rerun_keys(self._reader(values), overridden_by=overridden_by) == []

    def it_skips_a_key_a_parsed_option_already_sets(self) -> None:
        values: dict[str, str | list[str]] = {'only_rerun': ['a '], 'rerun_except': ['b ']}

        assert unforwardable_rerun_keys(self._reader(values), option_keys_set={'only_rerun'}) == ['rerun_except']

    def it_leaves_the_offending_list_out_of_the_overrides(self) -> None:
        values: dict[str, str | list[str]] = {'reruns': '2', 'rerun_except': ['a ']}

        assert rerun_ini_overrides(self._reader(values)) == ['--override-ini=reruns=2']


def _resets(*keys: str) -> list[str]:
    return [f'--override-ini={key}=' for key in keys]


_ALL_RERUN_KEYS = ('reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except')

# Every rerun ini key set to a value ``--override-ini`` carries unchanged.
_EVERY_RERUN_KEY_SET: dict[str, str | list[str]] = {
    'reruns': '2',
    'reruns_delay': '2',
    'reruns_delay_backoff_factor': '2',
    'only_rerun': ['a'],
    'rerun_except': ['a'],
}


def _all_rerun_keys_except(key: str) -> list[str]:
    return [other for other in _ALL_RERUN_KEYS if other != key]


def _keys_of(overrides: list[str]) -> list[str]:
    """Return the ini key of each ``--override-ini=key=value`` argument, in order."""
    return [override.removeprefix('--override-ini=').partition('=')[0] for override in overrides]


def _reader_raising(errors: Mapping[str, Exception], values: dict[str, str] | None = None) -> Callable[[str], object]:
    """Return a ``config.getini`` stand-in that raises the error given for a key and reads others from ``values``."""
    known_values = values or {}

    def read_ini(key: str) -> object:
        if key in errors:
            raise errors[key]
        return known_values.get(key, [] if key in ('only_rerun', 'rerun_except') else '')

    return read_ini


@pytest.mark.small
class DescribeRerunResets:
    _reader = staticmethod(_ini_reader)

    def it_resets_each_key_that_is_unset(self) -> None:
        assert rerun_resets(self._reader({'reruns': '2'})) == _resets(
            'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except'
        )

    def it_resets_an_unset_delay_so_the_project_file_cannot_make_gremlin_runs_wait(self) -> None:
        assert '--override-ini=reruns_delay=' in rerun_resets(self._reader({'reruns': '2'}))

    @pytest.mark.parametrize('unset', [None, '', []])
    def it_treats_every_empty_value_as_unset(self, unset: object) -> None:
        assert rerun_resets(lambda _key: unset) == _resets(*_ALL_RERUN_KEYS)

    def it_resets_a_list_key_whose_items_pytest_would_change(self) -> None:
        values: dict[str, str | list[str]] = {
            'reruns': '2',
            'reruns_delay': '1',
            'reruns_delay_backoff_factor': '2',
            'only_rerun': ['a'],
            'rerun_except': ['b '],
        }

        assert rerun_resets(self._reader(values)) == _resets('rerun_except')

    def it_leaves_every_key_alone_when_it_is_forwarded(self) -> None:
        values: dict[str, str | list[str]] = {
            'reruns': '2',
            'reruns_delay': '1',
            'reruns_delay_backoff_factor': '2',
            'only_rerun': ['a'],
            'rerun_except': ['b c'],
        }

        assert rerun_resets(self._reader(values)) == []

    @pytest.mark.parametrize(
        ('overridden_by', 'key'),
        [
            (['--override-ini=only_rerun=a'], 'only_rerun'),
            (['--only-rerun=a'], 'only_rerun'),
            (['--reruns-delay=1'], 'reruns_delay'),
            (['--reruns=2'], 'reruns'),
            (['--reruns-delay-backoff-factor=2'], 'reruns_delay_backoff_factor'),
            (['--rerun-except=a'], 'rerun_except'),
            (['--override-ini=reruns_delay=1'], 'reruns_delay'),
        ],
    )
    def it_leaves_alone_a_key_the_command_line_already_overrides(self, overridden_by: list[str], key: str) -> None:
        resets = rerun_resets(self._reader({}), overridden_by=overridden_by)

        assert resets == _resets(*_all_rerun_keys_except(key))

    @pytest.mark.parametrize('key', _ALL_RERUN_KEYS)
    def it_leaves_alone_a_key_a_parsed_option_already_sets(self, key: str) -> None:
        resets = rerun_resets(self._reader({}), option_keys_set=[key])

        assert resets == _resets(*_all_rerun_keys_except(key))

    def it_skips_a_key_the_installed_pytest_rerunfailures_does_not_register(self) -> None:
        read_ini = _reader_raising({'only_rerun': ValueError('only_rerun')})

        expected = _resets('reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'rerun_except')
        assert rerun_resets(read_ini) == expected

    def it_resets_a_key_pytest_cannot_read_as_a_string_because_the_project_file_could_set_it(self) -> None:
        read_ini = _reader_raising({'reruns_delay': TypeError('reruns_delay')}, {'reruns': '2'})

        assert rerun_resets(read_ini) == _resets(*_all_rerun_keys_except('reruns'))


@pytest.mark.small
class DescribeRerunKeysSetIn:
    @pytest.mark.parametrize('key', _ALL_RERUN_KEYS)
    def it_names_a_key_whose_parsed_option_is_set(self, key: str) -> None:
        assert rerun_keys_set_in(SimpleNamespace(**{key: 'value'})) == {key}

    def it_ignores_an_option_left_at_its_default(self) -> None:
        option = SimpleNamespace(**dict.fromkeys(_ALL_RERUN_KEYS))

        assert rerun_keys_set_in(option) == set()

    def it_counts_a_falsy_value_as_set(self) -> None:
        assert rerun_keys_set_in(SimpleNamespace(reruns=0)) == {'reruns'}

    def it_ignores_options_the_namespace_does_not_have(self) -> None:
        assert rerun_keys_set_in(SimpleNamespace()) == set()


@pytest.mark.small
class DescribeKeysACommandLineOptionOverrides:
    @pytest.mark.parametrize(
        ('option', 'key'),
        [
            ('--reruns=2', 'reruns'),
            ('--reruns-delay=1', 'reruns_delay'),
            ('--reruns-delay-backoff-factor=2', 'reruns_delay_backoff_factor'),
            ('--only-rerun=a', 'only_rerun'),
            ('--rerun-except=a', 'rerun_except'),
            ('--override-ini=only_rerun=a', 'only_rerun'),
        ],
    )
    def it_keeps_the_ini_key_it_replaces_out_of_the_forwarded_overrides(self, option: str, key: str) -> None:
        forwarded = rerun_ini_overrides(_ini_reader(_EVERY_RERUN_KEY_SET), overridden_by=[option])

        assert _keys_of(forwarded) == _all_rerun_keys_except(key)

    def it_does_not_report_a_key_a_command_line_option_replaces(self) -> None:
        values: dict[str, str | list[str]] = {'only_rerun': ['a '], 'rerun_except': ['b ']}
        reader = _ini_reader(values)

        assert unforwardable_rerun_keys(reader, overridden_by=['--only-rerun=a']) == ['rerun_except']


@pytest.mark.small
class DescribeUnforwardedRerunKeyWarning:
    def it_names_the_key_and_says_gremlin_runs_rerun_more_failures(self) -> None:
        warning = unforwarded_rerun_key_warning('only_rerun')

        assert warning.startswith('pytest-gremlins: warning:')
        assert "'only_rerun'" in warning
        assert 'not carried into gremlin runs' in warning
        assert 'rerun more failures than the baseline' in warning
        assert 'no filter' in warning
        assert '\n' not in warning


@pytest.mark.small
class DescribeRerunIniOverrides:
    _reader = staticmethod(_ini_reader)

    def it_returns_nothing_when_no_rerun_ini_key_is_set(self) -> None:
        assert rerun_ini_overrides(self._reader({})) == []

    def it_forwards_each_set_key_as_an_ini_override_in_a_fixed_order(self) -> None:
        values: dict[str, str | list[str]] = {'reruns_delay': '0.5', 'reruns': '2', 'reruns_delay_backoff_factor': '2'}

        assert rerun_ini_overrides(self._reader(values)) == [
            '--override-ini=reruns=2',
            '--override-ini=reruns_delay=0.5',
            '--override-ini=reruns_delay_backoff_factor=2',
        ]

    def it_joins_a_list_setting_with_newlines_so_pytest_parses_the_same_list(self) -> None:
        values: dict[str, str | list[str]] = {
            'only_rerun': ['no such failure', 'AssertionError'],
            'rerun_except': ['X'],
        }

        assert rerun_ini_overrides(self._reader(values)) == [
            '--override-ini=only_rerun=no such failure\nAssertionError',
            '--override-ini=rerun_except=X',
        ]

    def it_skips_a_key_the_installed_pytest_rerunfailures_does_not_register(self) -> None:
        unregistered = ValueError('unknown configuration value')
        read_ini = _reader_raising(dict.fromkeys(_all_rerun_keys_except('reruns'), unregistered), {'reruns': '2'})

        assert rerun_ini_overrides(read_ini) == ['--override-ini=reruns=2']

    def it_skips_a_key_pytest_cannot_read_as_a_string_and_forwards_the_rest(self) -> None:
        read_ini = _reader_raising({'reruns': TypeError("expected str, got int for 'reruns'")}, {'reruns_delay': '0.5'})

        assert rerun_ini_overrides(read_ini) == ['--override-ini=reruns_delay=0.5']

    def it_leaves_out_a_key_a_parsed_option_already_sets(self) -> None:
        overrides = rerun_ini_overrides(_ini_reader(_EVERY_RERUN_KEY_SET), option_keys_set={'reruns', 'only_rerun'})

        assert _keys_of(overrides) == ['reruns_delay', 'reruns_delay_backoff_factor', 'rerun_except']

    def it_keeps_a_zero_count_from_a_toml_file_so_it_still_overrides_the_gremlin_runs_own_config(self) -> None:
        assert rerun_ini_overrides(self._reader({'reruns': 0})) == ['--override-ini=reruns=0']  # type: ignore[dict-item]

    def it_converts_a_non_string_value_from_a_toml_file_to_text(self) -> None:
        assert rerun_ini_overrides(self._reader({'reruns': 2})) == ['--override-ini=reruns=2']  # type: ignore[dict-item]
