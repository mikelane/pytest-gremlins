"""The one place ``PYTEST_ADDOPTS`` and ``addopts`` strings are split into tokens.

Three readers need different views of the variable.  Gremlin runs inherit its tokens, so they
need a list that tolerates a malformed value.  The subprocess environment scrubbers re-quote what
they keep, so they need the strict split and let a malformed value raise.  Both views share the
same ``shlex`` split.
"""

from __future__ import annotations

from collections.abc import Mapping
import shlex

PYTEST_ADDOPTS_ENV_VAR = 'PYTEST_ADDOPTS'


def split_addopts(addopts: str) -> list[str]:
    """Return the tokens of an ``addopts`` string, split as a POSIX shell would.

    Args:
        addopts: A pytest ``addopts`` string, as written in the ini file or ``PYTEST_ADDOPTS``.

    Returns:
        The tokens, with quoting removed.

    Raises:
        ValueError: If ``addopts`` has unbalanced quotes.

    Example:
        >>> split_addopts('-k "a or b" -v')
        ['-k', 'a or b', '-v']
        >>> split_addopts('')
        []
    """
    return shlex.split(addopts)


def inherited_addopts_tokens(env: Mapping[str, str]) -> list[str]:
    """Return the tokens of ``PYTEST_ADDOPTS`` in ``env``; unset, empty or malformed contributes none.

    Args:
        env: The environment to read.

    Returns:
        The tokens, or an empty list when the variable is unset, empty or has unbalanced quotes.

    Example:
        >>> inherited_addopts_tokens({'PYTEST_ADDOPTS': '-x -k "a or b"'})
        ['-x', '-k', 'a or b']
        >>> inherited_addopts_tokens({})
        []
        >>> inherited_addopts_tokens({'PYTEST_ADDOPTS': '-k "unbalanced'})
        []
    """
    try:
        return split_addopts(env.get(PYTEST_ADDOPTS_ENV_VAR, ''))
    except ValueError:
        return []
