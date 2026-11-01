"""The coverage pre-scan runs with ``-p no:gremlins`` and must not see this plugin's options."""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from pytest_gremlins.gremlins_options import (
    GREMLINS_FLAG_ONLY_OPTS,
    GREMLINS_VALUE_OPTS,
    addopts_without_gremlins,
    option_tables_from,
    option_takes_value,
)
from pytest_gremlins.plugin import (
    _prescan_env,
    pytest_addoption,
)


class _OptionRecorder:
    """Stands in for both ``pytest.Parser`` and its option group; records each ``addoption`` call."""

    def __init__(self) -> None:
        self.options: dict[str, dict[str, Any]] = {}

    def getgroup(self, *_args: object, **_kwargs: object) -> _OptionRecorder:
        return self

    def addoption(self, *names: str, **kwargs: Any) -> None:
        for name in names:
            self.options[name] = kwargs


def _registered_options() -> dict[str, dict[str, Any]]:
    recorder = _OptionRecorder()
    pytest_addoption(recorder)  # type: ignore[arg-type]
    return recorder.options


_PRE_DERIVATION_VALUE_OPTS = frozenset(
    {
        '--gremlin-operators',
        '--gremlin-report',
        '--gremlin-targets',
        '--gremlin-exclude',
        '--gremlin-workers',
        '--gremlin-batch-size',
        '--gremlin-coverage-timeout',
        '--gremlin-mutant-timeout',
        '--gremlins-html-dir',
        '--gremlin-max-pardons-pct',
        '--max-pardons',
        '--gremlin-executor',
        '--gremlin-explain',
    }
)
_PRE_DERIVATION_FLAG_ONLY_OPTS = frozenset(
    {
        '--gremlins',
        '--gremlin-cache',
        '--gremlin-clear-cache',
        '--gremlin-parallel',
        '--gremlin-batch',
        '--strict-pardons',
        '--gremlin-audit-pardons',
        '--gremlin-no-coverage-filter',
    }
)


@pytest.mark.small
class DescribeGremlinsOptionTables:
    """The stripper's tables are derived from ``pytest_addoption``, so a new option needs no second edit."""

    def it_derives_the_flag_only_table_the_hand_maintained_one_listed(self) -> None:
        assert GREMLINS_FLAG_ONLY_OPTS == _PRE_DERIVATION_FLAG_ONLY_OPTS

    def it_derives_the_value_table_the_hand_maintained_one_listed(self) -> None:
        assert GREMLINS_VALUE_OPTS == _PRE_DERIVATION_VALUE_OPTS

    def it_tables_every_registered_option_exactly_once(self) -> None:
        assert set(_registered_options()) == GREMLINS_FLAG_ONLY_OPTS | GREMLINS_VALUE_OPTS
        assert not GREMLINS_FLAG_ONLY_OPTS & GREMLINS_VALUE_OPTS


@pytest.mark.small
class DescribeOptionTablesFrom:
    def it_classifies_a_new_option_without_any_table_edit(self) -> None:
        def register(parser: Any) -> None:
            parser.addoption('--brand-new', action='store_true')
            parser.addoption('--brand-new-value', action='store')

        value_opts, flag_opts = option_tables_from(register)

        assert (value_opts, flag_opts) == (frozenset({'--brand-new-value'}), frozenset({'--brand-new'}))

    def it_tables_the_negated_spelling_of_a_boolean_optional_action_as_a_flag(self) -> None:
        value_opts, flag_opts = option_tables_from(
            lambda p: p.addoption('--toggle', action=argparse.BooleanOptionalAction)
        )

        assert (value_opts, flag_opts) == (frozenset(), frozenset({'--toggle', '--no-toggle'}))

    def it_ignores_ini_registrations_made_by_pytest_addoption(self) -> None:
        def register(parser: Any) -> None:
            parser.addini('gremlin_thing', 'help')
            parser.getgroup('g').addoption('--new-flag', action='store_true')

        assert option_tables_from(register) == (frozenset(), frozenset({'--new-flag'}))


@pytest.mark.small
class DescribeOptionTakesValue:
    @pytest.mark.parametrize('action', ['store_true', 'store_false', 'store_const', 'count', 'append_const'])
    def it_treats_value_less_actions_as_flags(self, action: str) -> None:
        assert not option_takes_value({'action': action})

    @pytest.mark.parametrize('kwargs', [{}, {'action': 'store'}, {'action': 'append'}, {'action': 'extend'}])
    def it_treats_value_consuming_actions_as_taking_a_value(self, kwargs: dict[str, Any]) -> None:
        assert option_takes_value(kwargs)

    def it_treats_nargs_zero_as_a_flag(self) -> None:
        assert not option_takes_value({'action': 'store', 'nargs': 0})

    def it_treats_boolean_optional_action_as_a_flag(self) -> None:
        assert not option_takes_value({'action': argparse.BooleanOptionalAction})

    def it_treats_a_custom_action_class_with_nargs_zero_as_a_flag(self) -> None:
        class Toggle(argparse.Action):
            def __init__(self, option_strings: Any, dest: Any, **kwargs: Any) -> None:
                super().__init__(option_strings, dest, nargs=0, **kwargs)

        assert not option_takes_value({'action': Toggle})

    def it_treats_a_custom_action_class_without_nargs_zero_as_taking_a_value(self) -> None:
        assert option_takes_value({'action': argparse.Action})

    def it_keeps_a_store_false_flag_from_eating_the_next_token(self) -> None:
        value_opts, flag_opts = option_tables_from(lambda p: p.addoption('--off', action='store_false'))

        assert (value_opts, flag_opts) == (frozenset(), frozenset({'--off'}))


@pytest.mark.small
class DescribeAddoptsWithoutGremlins:
    def it_strips_an_inline_value_option(self) -> None:
        assert addopts_without_gremlins('--gremlin-report=json -v') == '-v'

    def it_strips_a_separate_value_option_and_its_value(self) -> None:
        assert addopts_without_gremlins('--gremlin-workers 4 -v') == '-v'

    def it_strips_flag_only_options_without_eating_the_next_token(self) -> None:
        assert addopts_without_gremlins('--gremlins -v --strict-pardons --import-mode=importlib') == (
            '-v --import-mode=importlib'
        )

    def it_strips_options_without_the_gremlin_prefix(self) -> None:
        assert addopts_without_gremlins('--max-pardons 3 --gremlins-html-dir=out') == ''

    def it_keeps_an_unrelated_option_sharing_the_prefix(self) -> None:
        assert addopts_without_gremlins('--gremlin-reporter=x') == '--gremlin-reporter=x'

    def it_requotes_kept_tokens(self) -> None:
        assert addopts_without_gremlins("-k 'a or b' --gremlins") == "-k 'a or b'"

    def it_keeps_every_token_after_the_end_of_options_marker(self) -> None:
        assert addopts_without_gremlins('-v --gremlins -- --gremlins --gremlin-workers 4') == (
            '-v -- --gremlins --gremlin-workers 4'
        )

    def it_keeps_a_positional_after_the_end_of_options_marker(self) -> None:
        assert addopts_without_gremlins('-v -- tests/test_a.py') == '-v -- tests/test_a.py'


@pytest.mark.small
class DescribePrescanEnv:
    def it_strips_gremlins_and_xdist_options_from_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 2 --gremlin-report=json --import-mode=importlib')

        assert _prescan_env()['PYTEST_ADDOPTS'] == '--import-mode=importlib'

    def it_strips_cov_options_from_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '--cov=target --cov-report term --import-mode=importlib')

        assert _prescan_env()['PYTEST_ADDOPTS'] == '--import-mode=importlib'

    def it_drops_pytest_addopts_when_only_cov_options_were_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '--cov --cov-fail-under=50')

        env = _prescan_env()
        has_addopts = 'PYTEST_ADDOPTS' in env
        del env  # --showlocals must not display the subprocess environment.
        assert not has_addopts

    def it_drops_pytest_addopts_when_only_gremlins_options_were_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '--gremlin-report=json --gremlin-workers 4')

        env = _prescan_env()
        has_addopts = 'PYTEST_ADDOPTS' in env
        del env  # --showlocals must not display the subprocess environment.
        assert not has_addopts
