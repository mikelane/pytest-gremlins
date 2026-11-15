"""Rerun options typed on the command line are carried into gremlin runs (refs #546)."""

from __future__ import annotations

import pytest

from pytest_gremlins.rerun_options import (
    baseline_rerun_warning,
    rerun_options_in,
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
