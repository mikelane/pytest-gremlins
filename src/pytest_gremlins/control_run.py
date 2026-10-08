"""Unmutated control run: can the gremlin subprocess load the suite at all?

A mutant that stops the suite from loading is caught by the suite, so the gremlin bootstrap reports
it with a dedicated exit code and the parent scores it as a kill. That attribution is only sound if
the *unmutated* suite loads in the same subprocess harness. The baseline run is a different process
with a different loader and command line, so it cannot vouch for that. This module runs the harness
once, with no active gremlin, in ``--collect-only`` mode, and explains the result.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import subprocess
import time
from typing import TYPE_CHECKING

from pytest_gremlins.node_id_file import command_with_node_ids_file

if TYPE_CHECKING:
    from collections.abc import (
        Mapping,
        Sequence,
    )
    from pathlib import Path

logger = logging.getLogger(__name__)

UNATTRIBUTABLE_MARKER = 'load_failures_unattributable'
"""File written next to ``sources.json`` when the control run failed; the bootstrap then stops
translating load failures into the collection-failed exit code."""

DIAGNOSTIC_TAIL_LINES = 20
"""Lines of the control run's output kept in the stderr diagnostic (counted in lines, unlike the cap below)."""

MAX_SELECTION_FAILURE_OUTPUT_CHARS = 2000
"""Characters of an unmutated selection's output kept in a downgraded result's ``error_output``."""

SELECTION_FAILS_TO_LOAD_PREFIX = (
    "the gremlin's own selection of tests fails to load even without a mutant, so the load failure "
    "can't be attributed to the mutant; output of the unmutated run:"
)
"""Start of the ``error_output`` of a collection kill that was downgraded to ERROR."""

TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX = (
    "timeout not counted as a kill: the gremlin's tests could not be launched without the mutant to confirm it; error:"
)
"""Start of the ``error_output`` of a timeout that cannot be confirmed due to a launch failure."""

CONTROL_RUN_TIMEOUT_SECONDS = 300
"""Seconds one control command may run before the suite counts as unable to load."""

_DIAGNOSTIC_INTRO = (
    'pytest-gremlins: the unmutated test suite fails to load in the gremlin subprocess, so load failures '
    "can't be attributed to mutants; they're reported as errors. Cause:"
)

_ANSI_SGR_SEQUENCE = re.compile(r'\x1b\[[0-9;]*m')

_HINTS = (
    (
        r'import file mismatch',
        'Hint: an option such as --import-mode was given only on the command line; put it in addopts '
        'so the gremlin subprocess receives it.',
    ),
    (
        r'^ERROR: not found:',
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


@dataclass(frozen=True)
class UnmutatedRunOutcome:
    """Result of running a gremlin's selection of tests without a mutant."""

    timed_out: bool
    seconds: float
    launch_error: str | None = None


def run_unmutated(
    command: Sequence[str],
    node_ids: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    *,
    timeout: int,
    node_ids_dir: Path | None = None,
) -> UnmutatedRunOutcome:
    """Run the given node ids with the gremlin bootstrap and no active gremlin, under a timeout.

    Only the time matters: a gremlin that timed out is a real kill only if the same selection
    finishes in time without the mutant, whatever its exit code.

    Args:
        command: The base gremlin test command (bootstrap script plus options).
        node_ids: Node ids the gremlin was asked to run, in command order.
        cwd: Directory to run in (the project root).
        env: Environment for the subprocess, without an active gremlin.
        timeout: Seconds the run may take, the same limit the gremlin ran under.
        node_ids_dir: Directory to hold a file of the node ids, so they stay off the command line (Windows
            caps it at 32,767 characters, #485). Without one the ids are appended to the command.

    Returns:
        Whether the run outlasted ``timeout``, and how long it took. If the run cannot be launched,
        a launch_error is set; this does not count as timing out, and the timeout confirmation
        becomes an ERROR result instead.
    """
    started = time.monotonic()
    try:
        subprocess.run(  # Intentional: runs the pytest bootstrap
            command_with_node_ids_file(command, node_ids, node_ids_dir),
            cwd=str(cwd),
            env=dict(env),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return UnmutatedRunOutcome(timed_out=True, seconds=time.monotonic() - started)
    except OSError as launch_error:
        logger.warning('Could not run the unmutated selection to confirm a timeout: %s', launch_error)
        return UnmutatedRunOutcome(timed_out=False, seconds=time.monotonic() - started, launch_error=str(launch_error))
    return UnmutatedRunOutcome(timed_out=False, seconds=time.monotonic() - started)


def build_diagnostic(output: str) -> str:
    """Build the stderr message for a failed control run, with hints for the common causes."""
    tail = '\n'.join(output.strip().splitlines()[-DIAGNOSTIC_TAIL_LINES:])
    uncolored = _ANSI_SGR_SEQUENCE.sub('', output)
    hints = [hint for pattern, hint in _HINTS if re.search(pattern, uncolored, re.MULTILINE)]
    return '\n'.join([_DIAGNOSTIC_INTRO, tail, *hints])


def run_control(
    command: Sequence[str],
    node_ids: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    *,
    timeout: int = CONTROL_RUN_TIMEOUT_SECONDS,
    node_ids_dir: Path | None = None,
) -> ControlRunOutcome:
    """Collect the given node ids with the gremlin bootstrap and no active gremlin.

    Args:
        command: The base gremlin test command (bootstrap script plus options).
        node_ids: Node ids the gremlins will select; empty collects the whole suite.
        cwd: Directory to run in (the project root).
        env: Environment for the subprocess, without an active gremlin.
        timeout: Seconds the run may take.
        node_ids_dir: Directory to hold a file of the node ids, so they stay off the command line (Windows
            caps it at 32,767 characters, #485). Without one the ids are appended to the command.

    Returns:
        Whether the suite collected cleanly, plus the run's output when it did not. A run that times out
        or cannot be launched does not load cleanly either, and its output says why.
    """
    started = time.monotonic()
    try:
        completed = subprocess.run(  # Intentional: runs the pytest bootstrap
            command_with_node_ids_file([*command, '--collect-only', '--tb=short'], node_ids, node_ids_dir),
            cwd=str(cwd),
            env=dict(env),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ControlRunOutcome(False, f'control run timed out after {timeout}s', time.monotonic() - started)
    except OSError as launch_error:
        logger.warning('Could not run the unmutated control run: %s', launch_error)
        return ControlRunOutcome(
            False, f'control run could not be launched: {launch_error}', time.monotonic() - started
        )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).decode(errors='replace')
        return ControlRunOutcome(False, output, time.monotonic() - started)
    return ControlRunOutcome(True, '', time.monotonic() - started)
