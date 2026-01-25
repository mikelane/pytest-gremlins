"""Configuration loading for pytest-gremlins.

This module reads configuration from pyproject.toml [tool.pytest-gremlins]
section and provides sensible defaults when configuration is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import tomllib
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class GremlinConfig:
    """Configuration for pytest-gremlins.

    All fields are optional and default to None, meaning the plugin
    will use CLI defaults or built-in defaults.

    Attributes:
        operators: List of mutation operator names to enable.
        paths: List of paths to scan for source files to mutate.
        exclude: List of glob patterns for files to exclude from mutation.
    """

    operators: list[str] | None = None
    paths: list[str] | None = None
    exclude: list[str] | None = None


def load_config(rootdir: Path) -> GremlinConfig:
    """Load configuration from pyproject.toml.

    Reads the [tool.pytest-gremlins] section from pyproject.toml in the
    given directory. Returns default configuration if the file or section
    does not exist.

    Args:
        rootdir: Directory containing pyproject.toml.

    Returns:
        GremlinConfig with values from pyproject.toml or defaults.
    """
    pyproject_path = rootdir / 'pyproject.toml'

    if not pyproject_path.exists():
        return GremlinConfig()

    with pyproject_path.open('rb') as f:
        data = tomllib.load(f)

    tool_config = data.get('tool', {}).get('pytest-gremlins', {})

    return GremlinConfig(
        operators=tool_config.get('operators'),
        paths=tool_config.get('paths'),
        exclude=tool_config.get('exclude'),
    )


def merge_configs(
    file_config: GremlinConfig,
    cli_operators: str | None = None,
    cli_targets: str | None = None,
) -> GremlinConfig:
    """Merge CLI arguments with file configuration.

    CLI arguments take precedence over pyproject.toml configuration.
    Empty strings are treated as not provided.

    Args:
        file_config: Configuration loaded from pyproject.toml.
        cli_operators: Comma-separated operator names from CLI (--gremlin-operators).
        cli_targets: Comma-separated target paths from CLI (--gremlin-targets).

    Returns:
        GremlinConfig with CLI values overriding file config where provided.
    """
    operators: list[str] | None = None
    if cli_operators and cli_operators.strip():
        operators = [op.strip() for op in cli_operators.split(',')]
    elif file_config.operators is not None:
        operators = file_config.operators

    paths: list[str] | None = None
    if cli_targets and cli_targets.strip():
        paths = [p.strip() for p in cli_targets.split(',')]
    elif file_config.paths is not None:
        paths = file_config.paths

    return GremlinConfig(
        operators=operators,
        paths=paths,
        exclude=file_config.exclude,
    )
