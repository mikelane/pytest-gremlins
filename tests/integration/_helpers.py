"""Helpers shared by the integration tests that run a mutation pass in a pytester subprocess."""

from __future__ import annotations

from pathlib import Path
import re

EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def verdicts(output: str) -> dict[str, int]:
    """Count the gremlins reported under each verdict label in the console summary."""

    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Timeout', 'Error')}


def mutant_rows(log: Path) -> list[list[str]]:
    """Return the tab-separated rows a test logged for each mutant, dropping the unmutated (NONE) rows."""
    rows = [line.split('\t') for line in log.read_text().splitlines()]
    return [row for row in rows if row[0] != 'NONE']
