"""The coverage pre-scan runs with ``-p no:gremlins`` and must not see this plugin's options."""

from __future__ import annotations

from typing import Any

import pytest

from pytest_gremlins.gremlins_options import (
    GREMLINS_FLAG_ONLY_OPTS,
    GREMLINS_VALUE_OPTS,
    addopts_without_gremlins,
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


@pytest.mark.small
class DescribeGremlinsOptionTables:
    """The stripper's tables must track ``pytest_addoption``, or a new option leaks into the pre-scan."""

    def it_lists_every_value_less_option_as_flag_only(self) -> None:
        flags = {name for name, kw in _registered_options().items() if kw.get('action') == 'store_true'}

        assert flags == GREMLINS_FLAG_ONLY_OPTS

    def it_lists_every_value_taking_option_as_value_taking(self) -> None:
        values = {name for name, kw in _registered_options().items() if kw.get('action') != 'store_true'}

        assert values == GREMLINS_VALUE_OPTS


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


@pytest.mark.small
class DescribePrescanEnv:
    def it_strips_gremlins_and_xdist_options_from_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 2 --gremlin-report=json --import-mode=importlib')

        assert _prescan_env()['PYTEST_ADDOPTS'] == '--import-mode=importlib'

    def it_drops_pytest_addopts_when_only_gremlins_options_were_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '--gremlin-report=json --gremlin-workers 4')

        assert 'PYTEST_ADDOPTS' not in _prescan_env()
