"""pytest-rerunfailures settings carried into the pytest subprocesses this plugin starts (issue #546).

A mutant is zapped when a covering test fails.  A flaky test that fails for reasons unrelated to the
mutation would zap every mutant it covers, unless the gremlin run reruns it the way the baseline did.
Rerun options in the project's ``addopts`` and ``PYTEST_ADDOPTS`` already reach gremlin runs, and so do the
ini settings of any config file pytest finds on its own, because a gremlin run discovers the same file.
This module carries the rerun options typed on the command line, and, only when a ``-c`` config file holds
the settings where the gremlin runs usually cannot read it, the rerun ini settings as ``--override-ini`` arguments.
pytest strips and splits the value of ``-o``, so a list setting whose items would change (issue #658)
is not carried.
A gremlin run under ``-c`` usually finds the project's own config file, which the baseline never read, so
every rerun ini key that is not carried is reset to empty: a filter list (``only_rerun``, ``rerun_except``)
then means no filter, an empty count means no reruns, and an empty delay or backoff factor means the
plugin's defaults (no delay, factor 1.0), exactly what the baseline ran with.
(A ``-c`` that reaches a gremlin run through ``PYTEST_ADDOPTS`` is read by that run too.)
A key is left alone when a parsed option already sets it, wherever it came from (the command line,
``addopts`` of the ``-c`` file or ``PYTEST_ADDOPTS``), because pytest-rerunfailures reads the option before
the ini key and the gremlin runs receive those sources themselves.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Collection,
    Sequence,
)
import locale
import math
from pathlib import Path
import re
import sys

from pytest_gremlins.config import MAX_TIMEOUT_SECONDS

_ARGUMENT_FILE_PREFIX = '@'

# argparse opens an ``@file`` with the locale encoding (strict) before Python 3.12 and with the filesystem
# encoding and error handler from 3.12 on.
_ARGPARSE_READS_LOCALE_ENCODING = sys.version_info < (3, 12)

# Every pytest-rerunfailures option that takes a value.  ``--fail-on-flaky`` is left out because it
# turns a test that passed on a rerun into exit code 7, which a gremlin run would not read as a kill;
# ``--rerun-show-tracebacks`` is left out because it only changes the output.
_RERUN_VALUE_OPTIONS = frozenset(
    {
        '--reruns',
        '--reruns-delay',
        '--reruns-delay-backoff-factor',
        '--reruns-mode',
        '--only-rerun',
        '--rerun-except',
        '--rerun-exclude-path',
        '--force-reruns',
        '--max-suite-reruns',
    }
)

# pytest-rerunfailures also reads these ini keys, so ``-o reruns=2`` is a command-line rerun option too.
_RERUN_INI_KEYS = frozenset({'reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except'})
# The order the settings are forwarded in; the list-valued keys are ``linelist`` ini options.
_FORWARDED_INI_KEYS = ('reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except')
# The command-line option pytest-rerunfailures reads before the ini key of the same setting.  Each such
# option is the ini key spelled as a long option, and its argparse ``dest`` is the ini key itself.
_OPTION_FOR_INI_KEY = {f'--{key.replace("_", "-")}': key for key in _FORWARDED_INI_KEYS}
_SHORT_OVERRIDE_INI = '-o'
_OVERRIDE_INI_ARGUMENT = '--override-ini='
_OVERRIDE_INI_OPTIONS = frozenset({_SHORT_OVERRIDE_INI, '--override-ini'})

# argparse reads ``-qo reruns=2`` as ``-q -o reruns=2``; only pytest's flags without a value may precede the ``o``.
_CLUSTERED_OVERRIDE_INI_PATTERN = re.compile(r'-[xqvlshV]*o(?P<attached>.*)', re.DOTALL)

# A line break inside an item splits it in two; a NUL byte makes the subprocess launch fail.
_UNSAFE_ITEM_CHARACTERS = frozenset('\n\r\x00')

_CARRIED_OPTIONS = _RERUN_VALUE_OPTIONS | _OVERRIDE_INI_OPTIONS

_MAX_NAMED_TESTS = 10


def _argparse_file_decoding() -> tuple[str, str]:
    """Return the encoding and error handler the running Python's argparse reads an ``@file`` with."""
    if _ARGPARSE_READS_LOCALE_ENCODING:
        return locale.getpreferredencoding(False), 'strict'
    return sys.getfilesystemencoding(), sys.getfilesystemencodeerrors()


def _expand_argument_files(args: Sequence[str], base_dir: Path, files_being_read: tuple[Path, ...] = ()) -> list[str]:
    """Replace each ``@file`` argument with the lines of that file, the way pytest's parser does.

    A file is decoded the way the running Python's argparse decodes it: with the locale encoding, strictly,
    before Python 3.12, and with the filesystem encoding and error handler from 3.12 on.
    A file that cannot be read or decoded, or that is already being read further up (a cycle), contributes
    nothing.
    pytest itself rejects an unreadable ``@file`` as a usage error and recurses without end on a cycle,
    so by the time this runs pytest has already read every file once; a read can fail here only if a
    file changed after pytest parsed it.
    """
    expanded: list[str] = []
    for arg in args:
        if not arg.startswith(_ARGUMENT_FILE_PREFIX):
            expanded.append(arg)
            continue
        argument_file = base_dir / arg[len(_ARGUMENT_FILE_PREFIX) :]
        if argument_file in files_being_read:
            continue
        try:
            encoding, errors = _argparse_file_decoding()
            lines = argument_file.read_text(encoding=encoding, errors=errors).splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        expanded.extend(_expand_argument_files(lines, base_dir, (*files_being_read, argument_file)))
    return expanded


def rerun_options_in(args: Sequence[str], *, base_dir: Path | None = None) -> list[str]:
    """Return the pytest-rerunfailures options in ``args``, each as one ``--name=value`` argument.

    The inline form is used so a value that starts with ``-`` cannot be mistaken for an option.
    ``@file`` arguments are expanded first, as pytest does, so options kept in an argument file count.

    Args:
        args: Command-line arguments, such as ``config.invocation_params.args``.
        base_dir: Directory that relative ``@file`` paths are resolved against; defaults to the
            current directory.  Use ``config.invocation_params.dir``.

    Returns:
        The rerun options in their original order; every other argument is dropped.  A ``-p`` plugin
        loader is never carried.

    Example:
        >>> rerun_options_in(['tests/', '--reruns', '2', '-x', '--reruns-delay=0.5'])
        ['--reruns=2', '--reruns-delay=0.5']
        >>> rerun_options_in(['-p', 'pytest_rerunfailures', '--reruns', '2'])
        ['--reruns=2']
    """
    expanded = _expand_argument_files(args, base_dir or Path())
    options: list[str] = []
    index = 0
    while index < len(expanded):
        arg = expanded[index]
        name, value = _split_option(arg)
        index += 1
        if name not in _CARRIED_OPTIONS:
            continue
        if value is None:
            if index == len(expanded):
                break
            value = expanded[index]
            index += 1
        option = _carried_form(name, value)
        if option is not None:
            options.append(option)
    return options


def _split_option(arg: str) -> tuple[str, str | None]:
    """Split ``arg`` into the option name and the value written in the same argument, if any."""
    clustered_match = _CLUSTERED_OVERRIDE_INI_PATTERN.fullmatch(arg)
    if clustered_match is not None:
        attached_value = clustered_match.group('attached')
        if not attached_value:
            return _SHORT_OVERRIDE_INI, None
        return _SHORT_OVERRIDE_INI, attached_value.removeprefix('=')
    name, has_inline_value, inline_value = arg.partition('=')
    return name, inline_value if has_inline_value else None


def _carried_form(name: str, value: str) -> str | None:
    """Return ``name`` and ``value`` as one argument, or None for an ini override that is not a rerun setting."""
    if name not in _OVERRIDE_INI_OPTIONS:
        return f'{name}={value}'
    if value.partition('=')[0] not in _RERUN_INI_KEYS:
        return None
    return f'{_OVERRIDE_INI_ARGUMENT}{value}'


def survives_override_ini(items: Sequence[str]) -> bool:
    r"""Return whether ``-o key=<items joined by newlines>`` makes pytest read back exactly ``items``.

    pytest splits the value of ``-o`` for a ``linelist`` key on newlines, strips each line and drops the
    empty ones.  An item with leading or trailing whitespace, with a line break inside, or an empty item
    therefore arrives changed.  An item with a NUL byte cannot be passed on a command line at all.

    Args:
        items: The items of a ``linelist`` ini setting, as ``config.getini`` returns them.

    Returns:
        True when every item is non-empty, has no surrounding whitespace and holds no line break or NUL byte.

    Example:
        >>> survives_override_ini(['Timeout', 'bad gateway'])
        True
        >>> survives_override_ini(['xyz '])
        False
        >>> survives_override_ini(['a\nb'])
        False
    """
    return all(item and item == item.strip() and not _UNSAFE_ITEM_CHARACTERS.intersection(item) for item in items)


def rerun_keys_set_in(option: object) -> set[str]:
    """Return the rerun ini keys whose parsed command-line option is set in ``option``.

    pytest-rerunfailures reads ``config.option.<key>`` before the ini key, so a key whose option holds a
    value is overridden, no matter whether the option came from the command line, ``addopts`` or
    ``PYTEST_ADDOPTS``.  An option left at its default of None is not set; a falsy value such as ``0`` is.

    Args:
        option: The parsed options, such as ``config.option``.

    Returns:
        The keys of the rerun ini settings whose option is set.

    Example:
        >>> from types import SimpleNamespace
        >>> sorted(rerun_keys_set_in(SimpleNamespace(reruns=0, only_rerun=None)))
        ['reruns']
    """
    return {key for key in _FORWARDED_INI_KEYS if getattr(option, key, None) is not None}


def _keys_overridden_by(overridden_by: Sequence[str], option_keys_set: Collection[str] = ()) -> set[str]:
    """Return the rerun ini keys that an option from :func:`rerun_options_in` or a parsed option overrides.

    Both ``--override-ini=key=...`` and the option pytest-rerunfailures reads instead of the key
    (``--only-rerun`` for ``only_rerun``) count, and so does every key in ``option_keys_set``.
    """
    overridden_keys: set[str] = set(option_keys_set)
    for option in overridden_by:
        if option.startswith(_OVERRIDE_INI_ARGUMENT):
            overridden_keys.add(option.removeprefix(_OVERRIDE_INI_ARGUMENT).partition('=')[0])
        elif (key := _OPTION_FOR_INI_KEY.get(option.partition('=')[0])) is not None:
            overridden_keys.add(key)
    return overridden_keys


def _read_not_overridden(
    read_ini: Callable[[str], object],
    overridden_by: Sequence[str],
    option_keys_set: Collection[str],
    *,
    unreadable_as_unset: bool = False,
) -> list[tuple[str, object]]:
    """Return each rerun ini key that nothing overrides and the installed plugin registers, with its value.

    A key ``read_ini`` cannot read as a string (``TypeError``) is skipped, or read as None when
    ``unreadable_as_unset`` is set; a key the plugin does not register (``ValueError``) is always skipped.
    """
    already_overridden = _keys_overridden_by(overridden_by, option_keys_set)
    unoverridden_settings: list[tuple[str, object]] = []
    for key in _FORWARDED_INI_KEYS:
        if key in already_overridden:
            continue
        try:
            unoverridden_settings.append((key, read_ini(key)))
        except TypeError:
            if unreadable_as_unset:
                unoverridden_settings.append((key, None))
        except ValueError:
            continue
    return unoverridden_settings


def _resolved_ini_settings(
    read_ini: Callable[[str], object], overridden_by: Sequence[str], option_keys_set: Collection[str]
) -> list[tuple[str, object]]:
    """Return each forwarded rerun ini key that is set and not overridden, with its value."""
    return [
        (key, value)
        for key, value in _read_not_overridden(read_ini, overridden_by, option_keys_set)
        if value not in (None, '', [])
    ]


def _is_changed_by_override_ini(value: object) -> bool:
    """Return whether ``value`` is a ``linelist`` value whose items ``-o`` would not pass unchanged."""
    return isinstance(value, list) and not survives_override_ini(value)


def rerun_ini_overrides(
    read_ini: Callable[[str], object], *, overridden_by: Sequence[str] = (), option_keys_set: Collection[str] = ()
) -> list[str]:
    r"""Return the pytest-rerunfailures ini settings the main session resolved, as ``--override-ini`` arguments.

    A gremlin run starts its own pytest, which is not given ``-c`` or ``--config-file`` (unless it comes
    through ``PYTEST_ADDOPTS``) and so does not read that file.  Passing the resolved values on the command
    line gives that run the settings the baseline ran with.  A setting that is unset or empty is left out.
    So is one the installed pytest-rerunfailures does not register (``config.getini`` raises ``ValueError``
    for it), and one pytest cannot read as a string (``config.getini`` raises ``TypeError`` for a number in
    native ``[tool.pytest]`` TOML, which pytest-rerunfailures also skips).

    A ``linelist`` setting (``only_rerun``, ``rerun_except``) is written one pattern per line, which is how
    pytest splits the value of ``-o``, so a pattern containing a space survives.  A list whose items pytest
    would change on the way (see :func:`survives_override_ini`) is left out, because a changed pattern
    reruns fewer failures than the baseline did and so zaps gremlins the tests did not earn; see
    :func:`unforwardable_rerun_keys` and :func:`rerun_resets`.

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        overridden_by: Options from :func:`rerun_options_in`.  A key one of them already overrides, as
            ``--override-ini`` or as the option of the same name (``--only-rerun``), is left out, so the
            command line is not contradicted or repeated.
        option_keys_set: Keys whose parsed option is set (see :func:`rerun_keys_set_in`), left out for
            the same reason.

    Returns:
        One ``--override-ini=key=value`` argument per set key.

    Example:
        >>> rerun_ini_overrides({'reruns': '2', 'only_rerun': ['Timeout', 'bad gateway']}.get)
        ['--override-ini=reruns=2', '--override-ini=only_rerun=Timeout\nbad gateway']
        >>> rerun_ini_overrides({'rerun_except': ['xyz ']}.get)
        []
    """
    overrides: list[str] = []
    for key, value in _resolved_ini_settings(read_ini, overridden_by, option_keys_set):
        if _is_changed_by_override_ini(value):
            continue
        override_value = '\n'.join(value) if isinstance(value, list) else value
        overrides.append(f'{_OVERRIDE_INI_ARGUMENT}{key}={override_value}')
    return overrides


def rerun_resets(
    read_ini: Callable[[str], object], *, overridden_by: Sequence[str] = (), option_keys_set: Collection[str] = ()
) -> list[str]:
    """Return an empty ``--override-ini`` for each rerun key the gremlin runs must not read from another file.

    Under ``-c`` a gremlin run finds the project's own config file.  A key that :func:`rerun_ini_overrides`
    does not carry, because the ``-c`` file leaves it unset (or pytest cannot read it), or because ``-o``
    would change the items of a list, would take its value from that file, which can restrict reruns or add
    a delay where the baseline had none.  ``--override-ini=key=`` makes pytest-rerunfailures fall back to
    what the baseline ran with: an empty ``only_rerun`` or ``rerun_except`` list is no filter, an empty
    ``reruns`` is no reruns (``int('')`` fails and the plugin ignores the error), and an empty
    ``reruns_delay`` or ``reruns_delay_backoff_factor`` is a delay of 0 and a factor of 1.0 (``float('')``
    fails likewise).  Every rerun key is then either forwarded or reset.

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        overridden_by: Options from :func:`rerun_options_in`; a key one of them overrides is left alone,
            because pytest-rerunfailures reads the option before any ini setting.
        option_keys_set: Keys whose parsed option is set (see :func:`rerun_keys_set_in`), left alone for
            the same reason.

    Returns:
        One ``--override-ini=key=`` argument per key that is unset or not carried.

    Example:
        >>> rerun_resets({'reruns': '2', 'reruns_delay': '1', 'only_rerun': ['Timeout'], 'rerun_except': ['xyz ']}.get)
        ['--override-ini=reruns_delay_backoff_factor=', '--override-ini=rerun_except=']
    """
    return [
        f'{_OVERRIDE_INI_ARGUMENT}{key}='
        for key, value in _read_not_overridden(read_ini, overridden_by, option_keys_set, unreadable_as_unset=True)
        if value in (None, '', []) or _is_changed_by_override_ini(value)
    ]


def unforwardable_rerun_keys(
    read_ini: Callable[[str], object], *, overridden_by: Sequence[str] = (), option_keys_set: Collection[str] = ()
) -> list[str]:
    """Return the rerun ini keys :func:`rerun_ini_overrides` leaves out because ``-o`` would change their items.

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        overridden_by: Options from :func:`rerun_options_in`; a key one of them overrides is not reported.
        option_keys_set: Keys whose parsed option is set (see :func:`rerun_keys_set_in`); not reported either.

    Returns:
        The keys, in the order the settings are forwarded in.

    Example:
        >>> unforwardable_rerun_keys({'reruns': '2', 'rerun_except': ['xyz ']}.get)
        ['rerun_except']
    """
    return [
        key
        for key, value in _resolved_ini_settings(read_ini, overridden_by, option_keys_set)
        if _is_changed_by_override_ini(value)
    ]


def unforwarded_rerun_key_warning(key: str) -> str:
    """Return the one-line warning that ``key`` is not carried into gremlin runs.

    Example:
        >>> unforwarded_rerun_key_warning('rerun_except').startswith('pytest-gremlins: warning:')
        True
    """
    return (
        f'pytest-gremlins: warning: the ini setting {key!r} is not carried into gremlin runs because some of its '
        'patterns cannot be passed unchanged on the command line (pytest strips and splits them, and a NUL byte '
        'cannot be passed at all); gremlin runs use no filter for it, so they rerun more failures than '
        'the baseline did, and some gremlins may survive that your tests would zap. To fix this, remove leading '
        'and trailing whitespace, line breaks, NUL bytes and empty items from its patterns, or move the setting to '
        'a config file pytest finds without -c'
    )


def baseline_rerun_warning(rerun_test_ids: Collection[str]) -> str | None:
    """Return the one-line warning for baseline tests that needed a rerun, or None if there were none.

    Args:
        rerun_test_ids: Node IDs of the baseline tests that failed at least once and were rerun.

    Returns:
        A warning naming up to ten of the tests, or None when no test needed a rerun.

    Example:
        >>> baseline_rerun_warning([]) is None
        True
        >>> baseline_rerun_warning(['t.py::test_flaky']).startswith('pytest-gremlins: warning:')
        True
    """
    if not rerun_test_ids:
        return None
    sorted_test_ids = sorted(rerun_test_ids)
    named_tests = ', '.join(sorted_test_ids[:_MAX_NAMED_TESTS])
    unnamed_count = len(sorted_test_ids) - _MAX_NAMED_TESTS
    if unnamed_count > 0:
        named_tests += f', and {unnamed_count} more'
    return (
        f'pytest-gremlins: warning: {len(sorted_test_ids)} baseline test(s) needed a rerun to pass: {named_tests}. '
        'Gremlin runs use the same rerun settings, so a gremlin is zapped only if these tests fail on every attempt; '
        'fix the flaky tests so your mutation score reflects your tests, not luck'
    )


def scaled_mutant_timeout(base: int, *, reruns: int, reruns_delay: float) -> int:
    """Return the per-mutant timeout widened to cover the reruns pytest-rerunfailures may make (issue #655).

    ``base`` is the budget of one attempt.  A killed mutant's covering test fails, is rerun ``reruns`` times
    and sleeps ``reruns_delay`` seconds before each rerun, so the run may need
    ``base * (reruns + 1) + ceil(reruns * reruns_delay)`` seconds before the mutant is judged.
    A negative or NaN delay counts as 0 (pytest-rerunfailures treats a negative one as 0).  No reruns leave
    ``base`` unchanged.  The result never exceeds ``MAX_TIMEOUT_SECONDS``.

    Args:
        base: Seconds one attempt may take.
        reruns: Reruns allowed per test; zero or less means none.
        reruns_delay: Seconds slept before each rerun.

    Returns:
        The timeout in whole seconds.

    Example:
        >>> scaled_mutant_timeout(30, reruns=2, reruns_delay=20)
        130
        >>> scaled_mutant_timeout(30, reruns=0, reruns_delay=20)
        30
    """
    if reruns <= 0:
        return base
    usable_delay = reruns_delay if reruns_delay > 0 else 0.0
    total_delay = reruns * usable_delay
    if total_delay >= MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    return min(base * (reruns + 1) + math.ceil(total_delay), MAX_TIMEOUT_SECONDS)


def session_rerun_budget(option: object, read_ini: Callable[[str], object]) -> tuple[int, float]:
    """Return the ``(reruns, reruns_delay)`` pytest-rerunfailures applies to a test with no ``flaky`` marker.

    This mirrors the plugin's own session-level reading: ``--force-reruns`` replaces the count outright;
    otherwise the ``--reruns`` option wins over the ``reruns`` ini key.  ``--reruns-delay`` wins over the
    ``reruns_delay`` ini key.  An ini value that is not a number, an ini key the installed plugin does not
    register, and an unset setting all count as no reruns and no delay.  A ``flaky`` marker on a test
    is not visible here and is not accounted for.

    Args:
        option: The parsed options, such as ``config.option``.
        read_ini: Reads an ini key as a string, such as ``config.getini``.

    Returns:
        The rerun count (0 when none) and the delay in seconds before each rerun (0.0 when none).

    Example:
        >>> from types import SimpleNamespace
        >>> session_rerun_budget(SimpleNamespace(reruns=None, reruns_delay=None), {'reruns': '2'}.get)
        (2, 0.0)
        >>> session_rerun_budget(SimpleNamespace(force_reruns=3, reruns_delay=1.5), {}.get)
        (3, 1.5)
    """
    return _session_reruns(option, read_ini), _session_reruns_delay(option, read_ini)


def _session_reruns(option: object, read_ini: Callable[[str], object]) -> int:
    for from_option in (getattr(option, 'force_reruns', None), getattr(option, 'reruns', None)):
        if from_option is not None:
            return int(from_option)
    return int(_read_number(read_ini, 'reruns', int))


def _session_reruns_delay(option: object, read_ini: Callable[[str], object]) -> float:
    from_option = getattr(option, 'reruns_delay', None)
    if from_option is not None:
        return float(from_option)
    return float(_read_number(read_ini, 'reruns_delay', float))


def _read_number(read_ini: Callable[[str], object], key: str, parse: Callable[[str], float]) -> float:
    try:
        return parse(str(read_ini(key)))
    except (TypeError, ValueError):
        return 0
