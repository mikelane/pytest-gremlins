"""Source-code diff utilities for gremlin mutation testing reports.

Provides helpers for converting AST nodes back to source strings and
computing unified diffs between original (Mogwai) and mutated (Gremlin) code.
"""

from __future__ import annotations

import ast
import difflib
import logging

logger = logging.getLogger(__name__)


def _node_to_source(node: ast.AST) -> str:
    """Convert an AST node to a source string using ast.unparse.

    Args:
        node: An AST node to unparse.

    Returns:
        Source code string for the node, or empty string if unparsing fails.
    """
    try:
        return ast.unparse(node)
    except Exception:
        logger.warning('Failed to get source for AST node', exc_info=True)
        return ''


def _compute_diff(original: str, mutated: str) -> list[str]:
    """Compute unified diff lines between original and mutated source.

    Args:
        original: The original (Mogwai) source string.
        mutated: The mutated (Gremlin) source string.

    Returns:
        List of unified diff lines with 3 context lines.
    """
    return list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            mutated.splitlines(keepends=True),
            fromfile='mogwai',
            tofile='gremlin',
            n=3,
        )
    )
