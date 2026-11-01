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
    Iterable,
    Sequence,
)
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import (
    TYPE_CHECKING,
    cast,
)

from pytest_gremlins.argument_files import expand_argument_files
from pytest_gremlins.config import MAX_TIMEOUT_SECONDS

if TYPE_CHECKING:
    import pytest

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

# The order the settings are forwarded in; the list-valued keys are ``linelist`` ini options.
_FORWARDED_INI_KEYS = ('reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except')
# pytest-rerunfailures also reads these ini keys, so ``-o reruns=2`` is a command-line rerun option too.
_RERUN_INI_KEYS = frozenset(_FORWARDED_INI_KEYS)
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

# pytest-rerunfailures' default ``reruns_delay_backoff_factor``: every rerun waits the same delay.
_NO_BACKOFF = 1.0


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
    expanded = expand_argument_files(args, base_dir or Path())
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
) -> list[tuple[str, object]]:
    """Return each rerun ini key that nothing overrides and the installed plugin registers, with its value.

    A key ``read_ini`` cannot read as a string (``TypeError``) reads as None; a key the plugin does not
    register (``ValueError``) is skipped.
    """
    already_overridden = _keys_overridden_by(overridden_by, option_keys_set)
    unoverridden_settings: list[tuple[str, object]] = []
    for key in _FORWARDED_INI_KEYS:
        if key in already_overridden:
            continue
        try:
            unoverridden_settings.append((key, read_ini(key)))
        except TypeError:
            unoverridden_settings.append((key, None))
        except ValueError:
            continue
    return unoverridden_settings


def _is_changed_by_override_ini(value: object) -> bool:
    """Return whether ``value`` is a ``linelist`` value whose items ``-o`` would not pass unchanged."""
    return isinstance(value, list) and not survives_override_ini(value)


@dataclass(frozen=True)
class RerunIniResolution:
    """What the gremlin runs are given for the rerun ini keys, from :func:`resolve_rerun_ini`.

    Attributes:
        overrides: ``--override-ini=key=value`` arguments carrying the settings the main session resolved.
        resets: ``--override-ini=key=`` arguments for each key the gremlin runs must not read from another file.
        unforwardable_keys: The keys left out of ``overrides`` because ``-o`` would change their items.
    """

    overrides: tuple[str, ...]
    resets: tuple[str, ...]
    unforwardable_keys: tuple[str, ...]


def resolve_rerun_ini(
    read_ini: Callable[[str], object], *, overridden_by: Sequence[str] = (), option_keys_set: Collection[str] = ()
) -> RerunIniResolution:
    r"""Resolve the pytest-rerunfailures ini settings the main session holds into what gremlin runs are given.

    A gremlin run starts its own pytest, which is not given ``-c`` or ``--config-file`` (unless it comes
    through ``PYTEST_ADDOPTS``) and so does not read that file.  Passing the resolved values on the command
    line gives that run the settings the baseline ran with.  Each key is read once and lands in exactly one
    place:

    * ``overrides``: the key is set, and carried as ``--override-ini``.  A setting that is unset or empty is
      left out.  So is one the installed pytest-rerunfailures does not register (``config.getini`` raises
      ``ValueError`` for it), and one pytest cannot read as a string (``config.getini`` raises ``TypeError``
      for a number in native ``[tool.pytest]`` TOML, which pytest-rerunfailures also skips).  A ``linelist``
      setting (``only_rerun``, ``rerun_except``) is written one pattern per line, which is how pytest splits
      the value of ``-o``, so a pattern containing a space survives.
    * ``unforwardable_keys``: the key is a list whose items pytest would change on the way (see
      :func:`survives_override_ini`).  It is left out of ``overrides`` because a changed pattern reruns fewer
      failures than the baseline did and so zaps gremlins the tests did not earn.
    * ``resets``: an empty ``--override-ini`` for each key that is unset, unreadable or unforwardable.  Under
      ``-c`` a gremlin run finds the project's own config file, which can restrict reruns or add a delay where
      the baseline had none.  ``--override-ini=key=`` makes pytest-rerunfailures fall back to what the baseline
      ran with: an empty ``only_rerun`` or ``rerun_except`` list is no filter, an empty ``reruns`` is no reruns
      (``int('')`` fails and the plugin ignores the error), and an empty ``reruns_delay`` or
      ``reruns_delay_backoff_factor`` is a delay of 0 and a factor of 1.0 (``float('')`` fails likewise).
      Every rerun key the plugin registers is then either forwarded or reset.

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        overridden_by: Options from :func:`rerun_options_in`.  A key one of them already overrides, as
            ``--override-ini`` or as the option of the same name (``--only-rerun``), is left out of all three
            results, so the command line is not contradicted or repeated.
        option_keys_set: Keys whose parsed option is set (see :func:`rerun_keys_set_in`), left out for
            the same reason.

    Returns:
        The overrides, resets and unforwardable keys, each in the order the settings are forwarded in.

    Example:
        >>> resolution = resolve_rerun_ini({'reruns': '2', 'only_rerun': ['Timeout', 'bad gateway']}.get)
        >>> resolution.overrides
        ('--override-ini=reruns=2', '--override-ini=only_rerun=Timeout\nbad gateway')
        >>> resolution = resolve_rerun_ini({'reruns': '2', 'rerun_except': ['xyz ']}.get)
        >>> resolution.unforwardable_keys, resolution.resets[-1]
        (('rerun_except',), '--override-ini=rerun_except=')
    """
    overrides: list[str] = []
    resets: list[str] = []
    unforwardable_keys: list[str] = []
    for key, value in _read_not_overridden(read_ini, overridden_by, option_keys_set):
        if _is_changed_by_override_ini(value):
            unforwardable_keys.append(key)
            resets.append(f'{_OVERRIDE_INI_ARGUMENT}{key}=')
        elif value in (None, '', []):
            resets.append(f'{_OVERRIDE_INI_ARGUMENT}{key}=')
        else:
            override_value = '\n'.join(value) if isinstance(value, list) else value
            overrides.append(f'{_OVERRIDE_INI_ARGUMENT}{key}={override_value}')
    return RerunIniResolution(tuple(overrides), tuple(resets), tuple(unforwardable_keys))


def rerun_ini_as_gremlin_runs_read(read_ini: Callable[[str], object], resets: Sequence[str]) -> Callable[[str], object]:
    """Return ``read_ini`` as the gremlin runs see it: a key in ``resets`` reads as empty.

    A reset (:func:`resolve_rerun_ini`) makes the gremlin runs ignore what the main session resolved for the key, so
    the incremental cache must key on the empty value, not on the file's (issue #677).

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        resets: The ``--override-ini=key=`` arguments from :func:`resolve_rerun_ini`.

    Returns:
        A reader that gives ``''`` for each reset key and defers to ``read_ini`` for the rest.

    Example:
        >>> ini = {'rerun_except': ['xyz '], 'reruns': '2'}.get
        >>> read = rerun_ini_as_gremlin_runs_read(ini, ['--override-ini=rerun_except='])
        >>> read('rerun_except'), read('reruns')
        ('', '2')
    """
    reset_keys = _keys_overridden_by(resets)

    def read(key: str) -> object:
        return '' if key in reset_keys else read_ini(key)

    return read


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


def scaled_mutant_timeout(
    base: int,
    *,
    reruns: int,
    reruns_delay: float,
    reruns_delay_backoff_factor: float = _NO_BACKOFF,
    delayed_tests: int = 1,
) -> int:
    """Return the per-mutant timeout widened to cover the reruns pytest-rerunfailures may make (issues #655, #672).

    ``base`` is the budget of one attempt.  A killed mutant's covering test fails, is rerun ``reruns`` times
    and sleeps ``reruns_delay * factor ** (n - 1)`` seconds before rerun ``n``, where ``factor`` is
    ``reruns_delay_backoff_factor``, so the run may need
    ``base * (reruns + 1) + ceil(reruns_delay * (1 + factor + ... + factor ** (reruns - 1)))`` seconds before
    the mutant is judged.  With the default factor of 1 that is ``ceil(reruns * reruns_delay)``.
    A negative or NaN delay counts as 0 (pytest-rerunfailures treats a negative one as 0), and a negative or NaN
    factor counts as 1 (it falls back to 1.0 for a negative one).  No reruns leave ``base`` unchanged.  The result
    never exceeds ``MAX_TIMEOUT_SECONDS``.  A run in which ``delayed_tests`` tests each wait out the delays (the
    coverage pre-scan, which runs the whole suite) pays that term once per test; ``base`` is not multiplied.

    Args:
        base: Seconds one attempt may take.
        reruns: Reruns allowed per test; zero or less means none.
        reruns_delay: Seconds slept before the first rerun.
        reruns_delay_backoff_factor: What the delay is multiplied by after each rerun.
        delayed_tests: Tests that wait out the delays in the run; zero or less counts as one.

    Returns:
        The timeout in whole seconds.

    Example:
        >>> scaled_mutant_timeout(30, reruns=2, reruns_delay=20)
        130
        >>> scaled_mutant_timeout(30, reruns=2, reruns_delay=1, reruns_delay_backoff_factor=3)
        94
        >>> scaled_mutant_timeout(30, reruns=0, reruns_delay=20)
        30
    """
    if reruns <= 0:
        return base
    if reruns >= MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    total_delay = _total_rerun_delay(reruns, reruns_delay, reruns_delay_backoff_factor) * max(1, delayed_tests)
    if total_delay >= MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    return min(base * (reruns + 1) + math.ceil(total_delay), MAX_TIMEOUT_SECONDS)


def flaky_marker_rerun_budget(marker: object) -> tuple[int, float, float]:
    """Return the ``(reruns, reruns_delay, backoff_factor)`` a ``flaky`` marker gives its test (issue #696).

    This mirrors pytest-rerunfailures: a keyword argument wins over the positional one, and a marker replaces
    the session budget outright, so a delay or factor it leaves out is 0 or 1.0, not the session's.  A bare
    ``@pytest.mark.flaky`` means one rerun.

    Args:
        marker: A ``pytest.Mark`` of the ``flaky`` marker, or anything with ``args`` and ``kwargs``.

    Returns:
        The rerun count, the delay in seconds before the first rerun and the factor the delay is multiplied by.

    Example:
        >>> from types import SimpleNamespace
        >>> flaky_marker_rerun_budget(SimpleNamespace(args=(3,), kwargs={'reruns_delay': 2}))
        (3, 2.0, 1.0)
    """
    args: tuple[object, ...] = getattr(marker, 'args', ())
    kwargs: dict[str, object] = getattr(marker, 'kwargs', {})
    reruns = _marker_argument(args, kwargs, 'reruns', 0, default=1)
    delay = _marker_argument(args, kwargs, 'reruns_delay', 1, default=0)
    factor = _marker_argument(args, kwargs, 'reruns_delay_backoff_factor', 2, default=_NO_BACKOFF)
    return _finite_rerun_count(reruns or 0), float(delay or 0), _NO_BACKOFF if factor is None else float(factor)


def _finite_rerun_count(reruns: float) -> int:
    """Return ``reruns`` as an int: infinity is the timeout cap and NaN is no reruns, which ``int()`` rejects."""
    if math.isnan(reruns):
        return 0
    if math.isinf(reruns):
        return MAX_TIMEOUT_SECONDS if reruns > 0 else 0
    return int(reruns)


def _marker_argument(
    args: tuple[object, ...], kwargs: dict[str, object], name: str, position: int, *, default: float
) -> float:
    if name in kwargs:
        return cast('float', kwargs[name])
    return cast('float', args[position]) if len(args) > position else default


def mutant_timeout_with_flaky_markers(base: int, *, session_timeout: int, markers: Iterable[object]) -> int:
    """Return ``session_timeout`` widened to the largest rerun budget any of ``markers`` asks for (issue #696).

    Each marker is scaled like :func:`scaled_mutant_timeout` scales the session budget, and the largest result
    wins.  A larger timeout is safe and a false timeout is not, so a marker smaller than the session budget
    changes nothing.

    Args:
        base: Seconds one attempt may take.
        session_timeout: The timeout already scaled for the session budget.
        markers: The ``flaky`` markers of the tests a run may execute.

    Returns:
        The timeout in whole seconds.

    Example:
        >>> from types import SimpleNamespace
        >>> marker = SimpleNamespace(args=(), kwargs={'reruns': 2, 'reruns_delay': 20})
        >>> mutant_timeout_with_flaky_markers(30, session_timeout=30, markers=[marker])
        130
    """
    timeout = session_timeout
    for marker in markers:
        reruns, reruns_delay, factor = flaky_marker_rerun_budget(marker)
        timeout = max(
            timeout,
            scaled_mutant_timeout(base, reruns=reruns, reruns_delay=reruns_delay, reruns_delay_backoff_factor=factor),
        )
    return timeout


def mutant_timeout_for_items(attempt_timeout: int, session_timeout: int, items: Iterable[pytest.Item]) -> int:
    """Return ``session_timeout`` widened to the largest ``@pytest.mark.flaky`` budget among ``items`` (issue #696).

    The closest marker wins, as it does for pytest-rerunfailures: one on a function replaces one on its class.
    The widest budget of any collected test applies to every gremlin, because a mutant's covering tests are
    not known when the timeout is fixed, and a larger timeout is safe where a false timeout is not.
    """
    markers = [marker for item in items if (marker := item.get_closest_marker('flaky')) is not None]
    return mutant_timeout_with_flaky_markers(attempt_timeout, session_timeout=session_timeout, markers=markers)


def _total_rerun_delay(reruns: int, reruns_delay: float, reruns_delay_backoff_factor: float) -> float:
    """Return the seconds pytest-rerunfailures sleeps over ``reruns`` reruns, ``inf`` when a float cannot hold it."""
    if not reruns_delay > 0:
        return 0.0
    factor = _usable_backoff_factor(reruns_delay_backoff_factor)
    if factor == _NO_BACKOFF:
        return reruns * reruns_delay
    # Sum the sleeps one by one: the closed form (factor**reruns - 1) / (factor - 1) cancels for a factor near 1
    # and can round the total down.  ``reruns`` is below MAX_TIMEOUT_SECONDS here, so the loop is bounded.
    try:
        total_delay = math.fsum(reruns_delay * factor**attempt for attempt in range(reruns))
    except OverflowError:
        return math.inf
    # An infinite delay times a zero factor's 0.0 makes NaN; the first rerun alone already sleeps forever.
    if math.isnan(total_delay):
        return math.inf
    return total_delay


def _usable_backoff_factor(factor: float) -> float:
    """Return ``factor``, or 1.0 where pytest-rerunfailures rejects it (negative) or sleeping on it would fail (NaN)."""
    return factor if factor >= 0 else _NO_BACKOFF


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


def session_rerun_backoff_factor(option: object, read_ini: Callable[[str], object]) -> float:
    """Return the ``reruns_delay_backoff_factor`` pytest-rerunfailures applies to a test with no ``flaky`` marker.

    The ``--reruns-delay-backoff-factor`` option wins over the ``reruns_delay_backoff_factor`` ini key.  An ini
    value that is not a number, an ini key the installed plugin does not register, and an unset setting all
    count as 1.0, and so does a negative factor, which the plugin replaces with 1.0 (and warns about).

    Args:
        option: The parsed options, such as ``config.option``.
        read_ini: Reads an ini key as a string, such as ``config.getini``.

    Returns:
        The factor the delay is multiplied by after each rerun.

    Example:
        >>> from types import SimpleNamespace
        >>> session_rerun_backoff_factor(SimpleNamespace(reruns_delay_backoff_factor=2.0), {}.get)
        2.0
        >>> session_rerun_backoff_factor(SimpleNamespace(), {}.get)
        1.0
    """
    from_option = getattr(option, 'reruns_delay_backoff_factor', None)
    if from_option is not None:
        return _usable_backoff_factor(float(from_option))
    return _usable_backoff_factor(
        float(_read_number(read_ini, 'reruns_delay_backoff_factor', float, default=_NO_BACKOFF))
    )


def rerun_cache_settings(option: object, read_ini: Callable[[str], object]) -> str:
    """Return the rerun settings beyond the count and delay that can change a verdict, as one cache-key string.

    The incremental cache keys a verdict on this (issue #677), because a run with ``--only-rerun ConnectionError``
    zaps a gremlin that a run without the filter would rerun past.  The settings are read the way
    pytest-rerunfailures reads them, not as the command line spelled them, so ``--only-rerun X`` and the
    ``only_rerun = X`` ini key give equal strings: the backoff factor as :func:`session_rerun_backoff_factor`
    resolves it, ``only_rerun`` and ``rerun_except`` from the option or else the ini key, and the options that
    have no ini key (``--rerun-exclude-path``, ``--reruns-mode``, ``--max-suite-reruns``) from the option.
    A filter or an exclusion is a set of patterns, so its order and repeats do not matter.  The count and delay
    are keyed separately (:func:`session_rerun_budget`).

    Args:
        option: The parsed options, such as ``config.option``.
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.

    Returns:
        A string that is equal for equal settings.

    Example:
        >>> from types import SimpleNamespace
        >>> rerun_cache_settings(SimpleNamespace(only_rerun=['B', 'A']), {}.get) == rerun_cache_settings(
        ...     SimpleNamespace(), {'only_rerun': ['A', 'B']}.get
        ... )
        True
        >>> rerun_cache_settings(SimpleNamespace(), {}.get) == rerun_cache_settings(
        ...     SimpleNamespace(max_suite_reruns=3), {}.get
        ... )
        False
    """
    settings = {
        'backoff': session_rerun_backoff_factor(option, read_ini),
        'only_rerun': _pattern_set(option, read_ini, 'only_rerun'),
        'rerun_except': _pattern_set(option, read_ini, 'rerun_except'),
        'exclude_path': _pattern_set(option, None, 'rerun_exclude_path'),
        'mode': getattr(option, 'reruns_mode', None),
        'max_suite_reruns': getattr(option, 'max_suite_reruns', None),
    }
    return json.dumps(settings, sort_keys=True)


def _pattern_set(option: object, read_ini: Callable[[str], object] | None, name: str) -> list[str]:
    """Return the sorted distinct patterns of ``name``: the option when it has any, else the ini key."""
    patterns = getattr(option, name, None)
    if not patterns and read_ini is not None:
        try:
            patterns = read_ini(name)
        except (TypeError, ValueError):
            patterns = None
    return sorted({str(pattern) for pattern in patterns or ()})


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


def _read_number(
    read_ini: Callable[[str], object], key: str, parse: Callable[[str], float], *, default: float = 0
) -> float:
    try:
        return parse(str(read_ini(key)))
    except (TypeError, ValueError):
        return default
