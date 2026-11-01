"""What the module-name integration tests share: the pytest arguments, execution modes and verdict parsing."""

from __future__ import annotations

import re

COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
    'xdist': ('-n', '2'),
}


def count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def verdicts(output: str) -> tuple[int, int, int]:
    """Return the zapped, survived and error counts of a report."""
    return count(output, 'Zapped'), count(output, 'Survived'), count(output, 'Error')
