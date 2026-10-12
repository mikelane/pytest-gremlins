"""pytest-rerunfailures settings carried into the pytest subprocesses this plugin starts (issue #546).

A mutant is zapped when a covering test fails.  A flaky test that fails for reasons unrelated to the
mutation would zap every mutant it covers, unless the gremlin run reruns it the way the baseline did.
Rerun options in the project's ``addopts`` and ``PYTEST_ADDOPTS`` already reach gremlin runs; this module
carries the ones typed on the command line and the rerun ini settings, which a ``-c`` config file holds
where the gremlin runs cannot read it.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Collection,
    Sequence,
)
import locale
from pathlib import Path
import re
import sys

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
_SHORT_OVERRIDE_INI = '-o'
_OVERRIDE_INI_ARGUMENT = '--override-ini='
_OVERRIDE_INI_OPTIONS = frozenset({_SHORT_OVERRIDE_INI, '--override-ini'})

# argparse reads ``-qo reruns=2`` as ``-q -o reruns=2``; only pytest's flags without a value may precede the ``o``.
_CLUSTERED_OVERRIDE_INI_PATTERN = re.compile(r'-[xqvlshV]*o(?P<attached>.*)', re.DOTALL)

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


def rerun_ini_overrides(read_ini: Callable[[str], object], *, overridden_by: Sequence[str] = ()) -> list[str]:
    r"""Return the pytest-rerunfailures ini settings the main session resolved, as ``--override-ini`` arguments.

    A gremlin run starts its own pytest, which does not read a config file named with ``-c`` or
    ``--config-file``.  Passing the resolved values on the command line gives that run the settings the
    baseline ran with.  A setting that is unset or empty is left out.  So is one the installed
    pytest-rerunfailures does not register (``config.getini`` raises ``ValueError`` for it), and one pytest
    cannot read as a string (``config.getini`` raises ``TypeError`` for a number in native ``[tool.pytest]``
    TOML, which pytest-rerunfailures also skips).

    A ``linelist`` setting (``only_rerun``, ``rerun_except``) is written one pattern per line, which is how
    pytest splits the value of ``-o``, so a pattern containing a space survives.

    Args:
        read_ini: Reads an ini key as the main session resolved it, such as ``config.getini``.
        overridden_by: Options from :func:`rerun_options_in`.  A key one of them already overrides is left
            out, so the command line is not contradicted or repeated.

    Returns:
        One ``--override-ini=key=value`` argument per set key.

    Example:
        >>> rerun_ini_overrides({'reruns': '2', 'only_rerun': ['Timeout', 'bad gateway']}.get)
        ['--override-ini=reruns=2', '--override-ini=only_rerun=Timeout\nbad gateway']
    """
    already_overridden = {
        option.removeprefix(_OVERRIDE_INI_ARGUMENT).partition('=')[0]
        for option in overridden_by
        if option.startswith(_OVERRIDE_INI_ARGUMENT)
    }
    overrides: list[str] = []
    for key in _FORWARDED_INI_KEYS:
        if key in already_overridden:
            continue
        try:
            value = read_ini(key)
        except (ValueError, TypeError):
            continue
        if isinstance(value, list):
            value = '\n'.join(value)
        if value not in (None, ''):
            overrides.append(f'{_OVERRIDE_INI_ARGUMENT}{key}={value}')
    return overrides


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
