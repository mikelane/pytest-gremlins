"""Configuration loading for pytest-gremlins.

This module reads configuration from pyproject.toml [tool.pytest-gremlins]
section and provides sensible defaults when configuration is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import tomllib
from tomllib import TOMLDecodeError
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


def _collect_setuptools_candidates(setuptools_config: dict[str, object]) -> list[str]:
    """Extract candidate source paths from setuptools configuration.

    Args:
        setuptools_config: The parsed [tool.setuptools] dictionary.

    Returns:
        List of candidate path strings (not yet validated against disk).
    """
    candidates: list[str] = []

    packages = setuptools_config.get('packages')
    if isinstance(packages, list):
        candidates.extend(pkg.split('.')[0] for pkg in packages)
    elif isinstance(packages, dict):
        find_config = packages.get('find', {})
        if isinstance(find_config, dict):
            where = find_config.get('where')
            if isinstance(where, list):
                candidates.extend(where)
            elif isinstance(where, str):
                candidates.append(where)

    package_dir = setuptools_config.get('package-dir')
    if isinstance(package_dir, dict):
        candidates.extend(v for v in package_dir.values() if v)

    return candidates


def discover_source_paths(rootdir: Path) -> list[str]:
    """Discover source paths from setuptools packaging metadata in pyproject.toml.

    Reads setuptools configuration as a fallback when [tool.pytest-gremlins].paths
    is not configured. Checks three locations in order:

    1. ``[tool.setuptools].packages`` -- explicit package list
    2. ``[tool.setuptools].package-dir`` -- directory mapping values
    3. ``[tool.setuptools.packages.find].where`` -- find-packages search roots

    Only paths that exist on disk are returned. Duplicates are removed while
    preserving discovery order.

    Args:
        rootdir: Directory containing pyproject.toml.

    Returns:
        List of discovered source path strings, or empty list if none found.

    Examples:
        >>> from pathlib import Path
        >>> discover_source_paths(Path('/nonexistent'))
        []
    """
    pyproject_path = rootdir / 'pyproject.toml'

    if not pyproject_path.exists():
        return []

    try:
        with pyproject_path.open('rb') as f:
            data = tomllib.load(f)
    except TOMLDecodeError:
        return []

    setuptools_config = data.get('tool', {}).get('setuptools', {})
    if not setuptools_config:
        return []

    candidates = _collect_setuptools_candidates(setuptools_config)

    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if candidate not in seen and (rootdir / candidate).is_dir():
            seen.add(candidate)
            result.append(candidate)

    return result


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
