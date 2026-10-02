"""Unmutated control run: can the gremlin subprocess load the suite at all?

A mutant that stops the suite from loading is caught by the suite, so the gremlin bootstrap reports
it with a dedicated exit code and the parent scores it as a kill. That attribution is only sound if
the *unmutated* suite loads in the same subprocess harness. The baseline run is a different process
with a different loader and command line, so it cannot vouch for that. This module runs the harness
once, with no active gremlin, in ``--collect-only`` mode, and explains the result.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import (
        Mapping,
        Sequence,
    )
    from pathlib import Path

UNATTRIBUTABLE_MARKER = 'load_failures_unattributable'
"""File written next to ``sources.json`` when the control run failed; the bootstrap then stops
translating load failures into the collection-failed exit code."""

MAX_NODE_ID_CHARS_PER_COMMAND = 50_000
"""Cap on node-id characters per control command, far below the OS argument-size limits."""

DIAGNOSTIC_TAIL_LINES = 20

SELECTION_FAILS_TO_LOAD_PREFIX = (
    "the gremlin's own selection of tests fails to load even without a mutant, so the load failure "
    "can't be attributed to the mutant; output of the unmutated run:"
)
"""Start of the ``error_output`` of a collection kill that was downgraded to ERROR."""

CONTROL_RUN_TIMEOUT_SECONDS = 300

_DIAGNOSTIC_INTRO = (
    'pytest-gremlins: the unmutated test suite fails to load in the gremlin subprocess, so load failures '
    "can't be attributed to mutants; they're reported as errors. Cause:"
)

_HINTS = (
    (
        '__file__',
        'Hint: a module reads __file__ at import time, but instrumented modules have no __file__ '
        '(see https://github.com/mikelane/pytest-gremlins/issues/525).',
    ),
    (
        'import file mismatch',
        'Hint: an option such as --import-mode was given only on the command line; put it in addopts '
        'so the gremlin subprocess receives it.',
    ),
    (
        'not found:',
        'Hint: a test id differs between processes (for example a parametrize id built from uuid, '
        'random or faker); make the ids deterministic.',
    ),
)


@dataclass(frozen=True)
class ControlRunOutcome:
    """Result of the unmutated control run."""

    loads_cleanly: bool
    output: str
    seconds: float


def chunk_node_ids(node_ids: Sequence[str], max_chars: int) -> list[list[str]]:
    """Split node ids into command-sized chunks.

    Args:
        node_ids: Node ids to pass on a command line.
        max_chars: Most characters (each id plus one separator) a chunk may hold.

    Returns:
        Chunks in order; a single id longer than the limit gets a chunk of its own.
        No node ids yield one empty chunk, so the whole suite is still collected once.
    """
    chunks: list[list[str]] = [[]]
    used = 0
    for node_id in node_ids:
        size = len(node_id) + 1
        if chunks[-1] and used + size > max_chars:
            chunks.append([])
            used = 0
        chunks[-1].append(node_id)
        used += size
    return chunks


def build_diagnostic(output: str) -> str:
    """Build the stderr message for a failed control run, with hints for the common causes."""
    tail = '\n'.join(output.strip().splitlines()[-DIAGNOSTIC_TAIL_LINES:])
    hints = [hint for needle, hint in _HINTS if needle in output]
    return '\n'.join([_DIAGNOSTIC_INTRO, tail, *hints])


def run_control(
    command: Sequence[str],
    node_ids: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    *,
    timeout: int = CONTROL_RUN_TIMEOUT_SECONDS,
    max_chars_per_command: int = MAX_NODE_ID_CHARS_PER_COMMAND,
) -> ControlRunOutcome:
    """Collect the given node ids with the gremlin bootstrap and no active gremlin.

    Args:
        command: The base gremlin test command (bootstrap script plus options).
        node_ids: Node ids the gremlins will select; empty collects the whole suite.
        cwd: Directory to run in (the project root).
        env: Environment for the subprocess, without an active gremlin.
        timeout: Seconds allowed per command.
        max_chars_per_command: Node-id characters per command before the ids are chunked.

    Returns:
        Whether every chunk collected cleanly, plus the output of the first failing one.
    """
    started = time.monotonic()
    for chunk in chunk_node_ids(node_ids, max_chars_per_command):
        try:
            completed = subprocess.run(  # Intentional: runs the pytest bootstrap
                [*command, '--collect-only', *chunk],
                cwd=str(cwd),
                env=dict(env),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ControlRunOutcome(False, f'control run timed out after {timeout}s', time.monotonic() - started)
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr).decode(errors='replace')
            return ControlRunOutcome(False, output, time.monotonic() - started)
    return ControlRunOutcome(True, '', time.monotonic() - started)
