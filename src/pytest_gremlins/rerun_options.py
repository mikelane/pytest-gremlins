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


def rerun_options_in(args: Sequence[str]) -> list[str]:
    """Return the pytest-rerunfailures options in ``args``, each as one ``--name=value`` argument.

    The inline form is used so a value that starts with ``-`` cannot be mistaken for an option.

    Args:
        args: Command-line arguments, such as ``config.invocation_params.args``.

    Returns:
        The rerun options in their original order; every other argument is dropped.

    Example:
        >>> rerun_options_in(['tests/', '--reruns', '2', '-x', '--reruns-delay=0.5'])
        ['--reruns=2', '--reruns-delay=0.5']
    """
    options: list[str] = []
    index = 0
    while index < len(args):
        name, has_inline_value, inline_value = args[index].partition('=')
        index += 1
        if name not in _RERUN_VALUE_OPTS:
            continue
        if has_inline_value:
            options.append(f'{name}={inline_value}')
        elif index < len(args):
            options.append(f'{name}={args[index]}')
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
