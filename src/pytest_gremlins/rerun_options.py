"""pytest-rerunfailures settings carried into the pytest subprocesses this plugin starts (issue #546).

A mutant is zapped when a covering test fails.  A flaky test that fails for reasons unrelated to the
mutation would zap every mutant it covers, unless the gremlin run reruns it the way the baseline did.
Rerun options in the project's ``addopts`` already reach gremlin runs, as do ``reruns`` ini settings
and ``PYTEST_ADDOPTS``; this module carries the ones typed on the command line.
"""

from __future__ import annotations

from collections.abc import (
    Collection,
    Sequence,
)
from pathlib import Path

_ARGUMENT_FILE_PREFIX = '@'

# Every pytest-rerunfailures option that takes a value.  ``--fail-on-flaky`` is left out because it
# turns a test that passed on a rerun into exit code 7, which a gremlin run would not read as a kill;
# ``--rerun-show-tracebacks`` is left out because it only changes the output.
_RERUN_VALUE_OPTS = frozenset(
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
_RERUN_INI_KEYS = frozenset({'reruns', 'reruns_delay'})
_OVERRIDE_INI_OPTS = frozenset({'-o', '--override-ini'})

_CARRIED_OPTS = _RERUN_VALUE_OPTS | _OVERRIDE_INI_OPTS

_MAX_NAMED_TESTS = 10


def _expand_argument_files(args: Sequence[str], base_dir: Path, files_being_read: tuple[Path, ...] = ()) -> list[str]:
    """Replace each ``@file`` argument with the lines of that file, the way pytest's parser does.

    A file that cannot be read, or that is already being read further up (a cycle), contributes nothing.
    """
    expanded: list[str] = []
    for arg in args:
        if not arg.startswith(_ARGUMENT_FILE_PREFIX):
            expanded.append(arg)
            continue
        path = base_dir / arg[len(_ARGUMENT_FILE_PREFIX) :]
        if path in files_being_read:
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, ValueError):
            continue
        expanded.extend(_expand_argument_files(lines, base_dir, (*files_being_read, path)))
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
        The rerun options in their original order; every other argument is dropped.

    Example:
        >>> rerun_options_in(['tests/', '--reruns', '2', '-x', '--reruns-delay=0.5'])
        ['--reruns=2', '--reruns-delay=0.5']
    """
    expanded = _expand_argument_files(args, base_dir or Path())
    options: list[str] = []
    index = 0
    while index < len(expanded):
        name, value = _split_option(expanded[index])
        index += 1
        if name not in _CARRIED_OPTS:
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
    if arg.startswith('-o') and not arg.startswith('--') and arg[2:3] not in ('', '='):
        return '-o', arg[2:]
    name, has_inline_value, inline_value = arg.partition('=')
    return name, inline_value if has_inline_value else None


def _carried_form(name: str, value: str) -> str | None:
    """Return ``name`` and ``value`` as one argument, or None for an ini override that is not a rerun setting."""
    if name not in _OVERRIDE_INI_OPTS:
        return f'{name}={value}'
    if value.partition('=')[0] not in _RERUN_INI_KEYS:
        return None
    return f'--override-ini={value}'


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
    ordered = sorted(rerun_test_ids)
    named = ', '.join(ordered[:_MAX_NAMED_TESTS])
    hidden = len(ordered) - _MAX_NAMED_TESTS
    if hidden > 0:
        named += f', and {hidden} more'
    return (
        f'pytest-gremlins: warning: {len(ordered)} baseline test(s) needed a rerun to pass: {named}. '
        'Gremlin runs use the same rerun settings, so a mutant is zapped only if these tests fail on every attempt; '
        'fix the flakiness to keep the score reliable'
    )
