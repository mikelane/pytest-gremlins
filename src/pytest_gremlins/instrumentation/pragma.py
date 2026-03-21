"""Inline suppression pragma parsing for gremlin mutation testing.

Parses ``# gremlin: pardon[<reason>] <justification>`` comments from Python
source code and returns a mapping of line numbers to (reason_code, justification)
tuples.  The pragma may appear on the same line as the code it pardons (inline)
or on the line immediately above (standalone comment).  Lines with invalid reason
codes or missing justification are logged as warnings and excluded from the result.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_VALID_REASON_CODES = frozenset({'equivalent', 'untestable', 'out_of_scope'})

_PRAGMA_RE = re.compile(
    r'#\s*gremlin:\s*pardon\[([^\]]*)\](.*)',
)


def _is_standalone_comment(line: str) -> bool:
    """Return True when *line* is a standalone comment (no code before the ``#``).

    Examples:
        >>> _is_standalone_comment('# gremlin: pardon[equivalent] reason')
        True

        >>> _is_standalone_comment('    # indented comment')
        True

        >>> _is_standalone_comment('x = 1  # inline comment')
        False
    """
    return line.lstrip().startswith('#')


def _validate_pragma(match: re.Match[str], *, lineno: int, file_path: str) -> tuple[str, str] | None:
    """Validate reason code and justification, logging warnings for invalid pragmas.

    Returns:
        ``(reason_code, justification)`` when valid, ``None`` otherwise.
    """
    reason_code = match.group(1).strip()
    justification = match.group(2).strip()

    if reason_code not in _VALID_REASON_CODES:
        logger.warning(
            'gremlin pragma at %s:%d has unknown reason code %r (valid codes: %s) — pragma ignored',
            file_path,
            lineno,
            reason_code,
            ', '.join(sorted(_VALID_REASON_CODES)),
        )
        return None

    if not justification:
        logger.warning(
            'gremlin pragma at %s:%d is missing a justification'
            ' (expected: # gremlin: pardon[reason] your justification) — pragma ignored',
            file_path,
            lineno,
        )
        return None

    return reason_code, justification


def _resolve_standalone_target(lines: list[str], *, lineno_index: int, lineno: int, file_path: str) -> int | None:
    """Determine the target line for a standalone pragma, or ``None`` if invalid.

    A standalone pragma must not be the last line and must be immediately
    followed by a non-blank line.
    """
    target_lineno = lineno + 1

    if target_lineno > len(lines):
        logger.warning(
            'gremlin pragma at %s:%d is a standalone comment on the last line — no code line below — pragma ignored',
            file_path,
            lineno,
        )
        return None

    next_line = lines[lineno_index + 1]
    if not next_line.strip():
        logger.warning(
            'gremlin pragma at %s:%d is not adjacent to a code line (blank line follows) — pragma ignored',
            file_path,
            lineno,
        )
        return None

    return target_lineno


def parse_pardoned_lines(source: str, *, file_path: str = '<unknown>') -> dict[int, tuple[str, str]]:
    r"""Parse inline suppression pragmas from Python source code.

    Scans each line for ``# gremlin: pardon[<reason>] <justification>``
    comments.  The pragma may appear in two positions:

    * **Inline** -- after code on the same line.  Pardons that line.
    * **Standalone** -- on a comment-only line immediately above the code.
      Pardons the next line.

    When both an inline and a standalone pragma target the same code line, the
    inline pragma wins and a warning is logged about the duplicate.

    Only lines with a valid reason code *and* non-empty justification are
    included in the result.  Invalid or incomplete pragmas are logged as
    warnings and skipped.

    Args:
        source: Raw Python source code as a string.
        file_path: Path to the source file, included in warning messages to
            identify the offending pragma without grepping the entire codebase.
            Defaults to ``'<unknown>'`` when no path is available.

    Returns:
        Mapping of 1-indexed line numbers to ``(reason_code, justification)``
        tuples for every valid suppression pragma found.

    Examples:
        >>> src = 'x = a // 2  # gremlin: pardon[equivalent] integer division\n'
        >>> parse_pardoned_lines(src)
        {1: ('equivalent', 'integer division')}

        >>> parse_pardoned_lines('x = 1  # normal comment\n')
        {}

        >>> above = '# gremlin: pardon[equivalent] floor div\nreturn a // b\n'
        >>> parse_pardoned_lines(above)
        {2: ('equivalent', 'floor div')}
    """
    lines = source.splitlines()

    inline_pragmas: dict[int, tuple[str, str]] = {}
    standalone_pragmas: dict[int, tuple[str, str]] = {}

    for lineno_index, line in enumerate(lines):
        lineno = lineno_index + 1
        match = _PRAGMA_RE.search(line)
        if match is None:
            continue

        validated = _validate_pragma(match, lineno=lineno, file_path=file_path)
        if validated is None:
            continue

        if _is_standalone_comment(line):
            target = _resolve_standalone_target(lines, lineno_index=lineno_index, lineno=lineno, file_path=file_path)
            if target is not None:
                standalone_pragmas[target] = validated
        else:
            inline_pragmas[lineno] = validated

    result = dict(standalone_pragmas)

    for target, value in inline_pragmas.items():
        if target in result:
            logger.warning(
                'gremlin pragma at %s:%d has both a line-above and same-line pardon'
                ' — using the same-line pragma (duplicate pardon)',
                file_path,
                target,
            )
        result[target] = value

    return result
