#!/usr/bin/env python3
"""Detect bare MagicMock()/Mock() calls without spec= or spec_set=."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MOCK_NAMES = frozenset({'MagicMock', 'Mock'})
SPEC_KWARGS = frozenset({'spec', 'spec_set'})
SUPPRESS_COMMENT = 'bare-mock: ok'


def check_file(filepath: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, mock_name) for bare mock calls in the file.

    Lines containing the comment ``# bare-mock: ok`` are suppressed.
    """
    violations: list[tuple[int, str]] = []
    try:
        source = filepath.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name) and func.id in MOCK_NAMES:
            name = func.id
        elif isinstance(func, ast.Attribute) and func.attr in MOCK_NAMES:
            name = func.attr
        if name is None:
            continue
        has_spec = any(kw.arg in SPEC_KWARGS for kw in node.keywords)
        if has_spec:
            continue
        line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ''
        if SUPPRESS_COMMENT in line_text:
            continue
        violations.append((node.lineno, name))
    return violations


def main() -> int:
    """Check files passed as CLI arguments for bare MagicMock/Mock calls."""
    filepaths = [Path(arg) for arg in sys.argv[1:]]
    found = False
    for filepath in filepaths:
        if not filepath.exists():
            continue
        for lineno, name in check_file(filepath):
            print(f'{filepath}:{lineno}: bare {name}() without spec= or spec_set=')
            found = True
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
