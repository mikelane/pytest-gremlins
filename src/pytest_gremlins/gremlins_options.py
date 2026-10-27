"""Removal of this plugin's own options from the coverage pre-scan, which runs with ``-p no:gremlins``."""

from __future__ import annotations

from collections.abc import (
    Callable,
    Mapping,
)
from functools import lru_cache
import shlex
from typing import Any

# argparse actions that never consume a value token (``help`` and ``version`` included).
_VALUE_LESS_ACTIONS = frozenset(
    {'store_true', 'store_false', 'store_const', 'append_const', 'count', 'help', 'version'}
)


class _OptionRecorder:
    """Stands in for ``pytest.Parser`` and its option group, recording each ``addoption`` call."""

    def __init__(self) -> None:
        self.options: dict[str, dict[str, object]] = {}

    def getgroup(self, *_args: object, **_kwargs: object) -> _OptionRecorder:
        return self

    def addoption(self, *names: str, **kwargs: object) -> None:
        for name in names:
            self.options[name] = kwargs


def option_takes_value(addoption_kwargs: Mapping[str, object]) -> bool:
    """Return True if argparse would consume a value token for an option registered with these kwargs.

    Example:
        >>> option_takes_value({'action': 'store_true'})
        False
        >>> option_takes_value({'action': 'append'})
        True
    """
    if addoption_kwargs.get('nargs') == 0:
        return False
    return addoption_kwargs.get('action', 'store') not in _VALUE_LESS_ACTIONS


def option_tables_from(register: Callable[[Any], None]) -> tuple[frozenset[str], frozenset[str]]:
    """Run ``register`` (a ``pytest_addoption``) against a recorder and classify what it registers.

    Returns:
        ``(value_options, flag_only_options)``.
    """
    recorder = _OptionRecorder()
    register(recorder)
    value_opts = frozenset(name for name, kwargs in recorder.options.items() if option_takes_value(kwargs))
    return value_opts, frozenset(recorder.options) - value_opts


@lru_cache(maxsize=1)
def _own_option_tables() -> tuple[frozenset[str], frozenset[str]]:
    from pytest_gremlins.plugin import pytest_addoption  # noqa: PLC0415 - plugin imports this module

    return option_tables_from(pytest_addoption)


def __getattr__(name: str) -> frozenset[str]:
    """Serve ``GREMLINS_VALUE_OPTS`` and ``GREMLINS_FLAG_ONLY_OPTS``, derived from ``pytest_addoption`` on first use."""
    if name == 'GREMLINS_VALUE_OPTS':
        return _own_option_tables()[0]
    if name == 'GREMLINS_FLAG_ONLY_OPTS':
        return _own_option_tables()[1]
    msg = f'module {__name__!r} has no attribute {name!r}'
    raise AttributeError(msg)


def addopts_without_gremlins(addopts: str) -> str:
    """Return ``addopts`` with this plugin's options removed.

    The coverage pre-scan runs ``pytest -p no:gremlins``, so these options are not
    registered there.  Left in ``PYTEST_ADDOPTS`` or the project's ``addopts``, any one
    of them is an unrecognized argument: the pre-scan exits 4, records nothing, and every
    gremlin runs the whole suite.  Value-taking options also drop their separate value arg.

    Args:
        addopts: A pytest ``addopts`` string, as written in the ini file or ``PYTEST_ADDOPTS``.

    Returns:
        ``addopts`` re-quoted with every pytest-gremlins option and its value removed.

    Example:
        >>> addopts_without_gremlins('--gremlin-report=json --import-mode=importlib')
        '--import-mode=importlib'
        >>> addopts_without_gremlins('--gremlins --gremlin-workers 4 -v')
        '-v'
    """
    value_opts, flag_only_opts = _own_option_tables()
    args = shlex.split(addopts)
    kept: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == '--':
            kept.extend(args[index - 1 :])
            break
        name = arg.split('=', 1)[0]
        if name in value_opts:
            if '=' not in arg:
                index += 1
        elif arg not in flag_only_opts:
            kept.append(arg)
    return ' '.join(shlex.quote(arg) for arg in kept)
