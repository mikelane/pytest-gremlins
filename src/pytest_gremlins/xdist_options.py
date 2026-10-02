"""Removal of pytest-xdist options from the pytest subprocesses this plugin starts."""

from __future__ import annotations

from collections.abc import Mapping
import shlex

# pytest-xdist options that take a value.  Written either inline (``--dist=load``) or
# with the value as the next token (``--dist load``).
_XDIST_VALUE_OPTS = frozenset(
    {
        '--numprocesses',
        '--maxprocesses',
        '--dist',
        '--max-worker-restart',
        '--tx',
        '--px',
        '--rsyncdir',
        '--rsyncignore',
        '--testrunuid',
        '--maxschedchunk',
    }
)

# pytest-xdist switches that take no value.
_XDIST_FLAG_ONLY_OPTS = frozenset(
    {'-d', '--distributed', '--loadscope-reorder', '--no-loadscope-reorder', '-f', '--looponfail'}
)


def _is_attached_short_numprocesses(arg: str) -> bool:
    """Return True for ``-n4`` / ``-nauto`` (the value glued to the short option)."""
    return arg.startswith('-n') and not arg.startswith('--') and len(arg) > len('-n')


def addopts_without_xdist(addopts: str) -> str:
    """Return ``addopts`` with pytest-xdist options removed.

    Distributing tests to xdist workers breaks two subprocesses this plugin starts.  The
    coverage pre-scan records nothing, because coverage.py does not trace workers, so
    coverage-guided selection silently degrades to running every test per gremlin (issue
    #502).  The per-gremlin bootstrap installs the gremlin import hook only in its own
    process, so workers import the original code and every gremlin falsely survives
    (issue #486).  ``-n``/``--numprocesses`` and the other xdist option families are
    therefore dropped; value-taking options also drop their separate value arg.  xdist
    stays loaded (``-p no:xdist`` would drop the ``worker_id`` fixture) and, without
    ``-n``, runs the tests in-process.

    Args:
        addopts: A pytest ``addopts`` string, as written in the ini file or ``PYTEST_ADDOPTS``.

    Returns:
        ``addopts`` re-quoted with every pytest-xdist option and its value removed.

    Example:
        >>> addopts_without_xdist('-n 4 --import-mode=importlib')
        '--import-mode=importlib'
        >>> addopts_without_xdist('-nauto --dist=loadscope -v')
        '-v'
    """
    args = shlex.split(addopts)
    kept: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        name = arg.split('=', 1)[0]
        takes_separate_value = (name in _XDIST_VALUE_OPTS and '=' not in arg) or arg == '-n'
        if takes_separate_value:
            index += 1
        elif name in _XDIST_VALUE_OPTS or arg in _XDIST_FLAG_ONLY_OPTS or _is_attached_short_numprocesses(arg):
            continue
        else:
            kept.append(arg)
    return ' '.join(shlex.quote(arg) for arg in kept)


def env_without_xdist_addopts(env: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` whose ``PYTEST_ADDOPTS`` has xdist options removed.

    pytest appends ``PYTEST_ADDOPTS`` to every invocation, so ``-n 2`` there distributes
    a subprocess just like ``-n 2`` in the project's ``addopts``.  The variable is dropped
    entirely if nothing remains.

    Args:
        env: The environment to copy; it is not modified.

    Returns:
        A new environment mapping without xdist options in ``PYTEST_ADDOPTS``.

    Example:
        >>> env_without_xdist_addopts({'PYTEST_ADDOPTS': '-n 2 -v', 'HOME': '/home/me'})
        {'HOME': '/home/me', 'PYTEST_ADDOPTS': '-v'}
        >>> env_without_xdist_addopts({'PYTEST_ADDOPTS': '-n auto'})
        {}
    """
    sanitized = dict(env)
    remaining = addopts_without_xdist(sanitized.pop('PYTEST_ADDOPTS', ''))
    if remaining:
        sanitized['PYTEST_ADDOPTS'] = remaining
    return sanitized
