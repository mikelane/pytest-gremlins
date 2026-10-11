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
        name, has_inline_value, inline_value = expanded[index].partition('=')
        index += 1
        if name not in _RERUN_VALUE_OPTS:
            continue
        if has_inline_value:
            options.append(f'{name}={inline_value}')
        elif index < len(expanded):
            options.append(f'{name}={expanded[index]}')
            index += 1
    return options


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
