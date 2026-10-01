"""Lightweight test runner command builder.

Shared utility for constructing lightweight runner commands that skip
full pytest startup overhead. Used by pool.py, persistent_pool.py,
and plugin.py.

The runner script is no longer written, so ``build_lightweight_command`` always returns
``None`` and every gremlin uses the pytest bootstrap. Disabled pending
https://github.com/mikelane/pytest-gremlins/issues/538.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE = 70
"""Exit code the runner uses to abstain; pytest uses 0-5 and 1 is reserved for a caught mutant."""

SAFE_TESTS_FILENAME = 'lightweight_safe_tests.json'
"""Sibling of the runner script listing node IDs the runner can judge faithfully."""


def describe_runner_error(returncode: int, stderr: bytes | None) -> str:
    """Build the ``error_output`` for a subprocess that exited with an error code.

    The runner's abstention code gets an explanatory prefix so the report says
    the verdict was withheld rather than showing a bare traceback.

    Args:
        returncode: Exit code of the test subprocess.
        stderr: Captured stderr, if any.

    Returns:
        Up to 2000 characters of stderr, prefixed for the runner's abstention code.
    """
    detail = stderr.decode(errors='replace')[:2000] if stderr else ''
    if returncode == LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE:
        return f'lightweight runner could not verify the selected tests: {detail}'.rstrip()
    return detail


def write_safe_tests(instrumented_dir: Path, safe_node_ids: Iterable[str]) -> None:
    """Record which node IDs the lightweight runner may execute.

    Written next to the runner script so every process that builds a lightweight
    command (including pool workers) reads the same answer without extra plumbing.

    Args:
        instrumented_dir: Directory holding the runner script and ``sources.json``.
        safe_node_ids: Node IDs of tests that pass ``is_lightweight_safe``.
    """
    (instrumented_dir / SAFE_TESTS_FILENAME).write_text(json.dumps(sorted(safe_node_ids)), encoding='utf-8')


def _load_safe_tests(instrumented_dir: Path) -> frozenset[str]:
    """Load the recorded safe node IDs; missing or unreadable means none are safe."""
    try:
        return frozenset(json.loads((instrumented_dir / SAFE_TESTS_FILENAME).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return frozenset()


def build_lightweight_command(
    test_command: list[str],
    env_vars: dict[str, str],
) -> list[str] | None:
    """Build a lightweight runner command if the runner script exists.

    Extracts test node IDs from the full test command and builds a
    command using the lightweight runner (no pytest overhead). The runner
    calls tests as bare callables, so it is only returned when every
    selected test was recorded as safe (see ``write_safe_tests``); otherwise
    the caller runs the full pytest bootstrap.

    Args:
        test_command: Original test command (e.g. [python, bootstrap.py, -x, ...]).
        env_vars: Environment variables that may contain sources file path.

    Returns:
        Lightweight command list, or None if the runner is unavailable or any
        selected test is not safe to run without pytest.
    """
    sources_file = env_vars.get('PYTEST_GREMLINS_SOURCES_FILE', '')
    if not sources_file:
        return None

    runner_path = Path(sources_file).parent / 'gremlin_lightweight_runner.py'
    if not runner_path.exists():
        return None

    # Extract test node IDs from test_command (args containing '::')
    test_ids = [arg for arg in test_command[2:] if '::' in arg]
    if not test_ids:
        return None

    if not frozenset(test_ids) <= _load_safe_tests(runner_path.parent):
        return None

    return [test_command[0], str(runner_path), *test_ids]
