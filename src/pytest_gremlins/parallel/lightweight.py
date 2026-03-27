"""Lightweight test runner command builder.

Shared utility for constructing lightweight runner commands that skip
full pytest startup overhead. Used by pool.py, persistent_pool.py,
and plugin.py.
"""

from __future__ import annotations

from pathlib import Path


def build_lightweight_command(
    test_command: list[str],
    env_vars: dict[str, str],
) -> list[str] | None:
    """Build a lightweight runner command if the runner script exists.

    Extracts test node IDs from the full test command and builds a
    command using the lightweight runner (no pytest overhead).

    Args:
        test_command: Original test command (e.g. [python, bootstrap.py, -x, ...]).
        env_vars: Environment variables that may contain sources file path.

    Returns:
        Lightweight command list, or None if the runner is not available.
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

    return [test_command[0], str(runner_path), *test_ids]
