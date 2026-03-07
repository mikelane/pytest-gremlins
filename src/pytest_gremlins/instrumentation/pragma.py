"""Inline suppression pragma parsing for gremlin mutation testing.

Parses ``# gremlin: survivor[<reason>] <justification>`` comments from Python
source code and returns a mapping of line numbers to (reason_code, justification)
tuples.  Lines with invalid reason codes or missing justification are logged as
warnings and excluded from the result.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_VALID_REASON_CODES = frozenset({'equivalent', 'untestable', 'out_of_scope'})

_PRAGMA_RE = re.compile(
    r'#\s*gremlin:\s*survivor\[([^\]]*)\](.*)',
)


def parse_pardoned_lines(source: str) -> dict[int, tuple[str, str]]:
    r"""Parse inline suppression pragmas from Python source code.

    Scans each line for ``# gremlin: survivor[<reason>] <justification>``
    comments.  Only lines with a valid reason code *and* non-empty justification
    are included in the result.  Invalid or incomplete pragmas are logged as
    warnings and skipped.

    Args:
        source: Raw Python source code as a string.

    Returns:
        Mapping of 1-indexed line numbers to ``(reason_code, justification)``
        tuples for every valid suppression pragma found.

    Examples:
        >>> src = 'x = a // 2  # gremlin: survivor[equivalent] integer division\n'
        >>> parse_pardoned_lines(src)
        {1: ('equivalent', 'integer division')}

        >>> parse_pardoned_lines('x = 1  # normal comment\n')
        {}
    """
    result: dict[int, tuple[str, str]] = {}

    for lineno, line in enumerate(source.splitlines(), start=1):
        match = _PRAGMA_RE.search(line)
        if match is None:
            continue

        reason_code = match.group(1).strip()
        justification = match.group(2).strip()

        if reason_code not in _VALID_REASON_CODES:
            logger.warning(
                'gremlin pragma on line %d has unknown reason code %r (valid codes: %s) — pragma ignored',
                lineno,
                reason_code,
                ', '.join(sorted(_VALID_REASON_CODES)),
            )
            continue

        if not justification:
            logger.warning(
                'gremlin pragma on line %d is missing a justification — pragma ignored',
                lineno,
            )
            continue

        result[lineno] = (reason_code, justification)

    return result
