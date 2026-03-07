"""Configuration loading for pytest-gremlins.

This module reads configuration from pyproject.toml [tool.pytest-gremlins]
section and provides sensible defaults when configuration is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import tomllib
from tomllib import TOMLDecodeError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GremlinConfig:
    """Configuration for pytest-gremlins.

    All fields are optional and default to None, meaning the plugin
    will use CLI defaults or built-in defaults.

    Attributes:
        operators: List of mutation operator names to enable.
        paths: List of paths to scan for source files to mutate.
        exclude: List of glob patterns for files to exclude from mutation.
        workers: Number of parallel workers, "auto" for CPU count, or None.
        cache: Whether to enable incremental analysis cache.
        report: Report format string (e.g. "console", "html", "json").
        batch_size: Number of gremlins per batch in batch mode.
    """

    operators: list[str] | None = None
    paths: list[str] | None = None
    exclude: list[str] | None = None
    workers: int | str | None = None
    cache: bool | None = None
    report: str | None = None
    batch_size: int | None = None
    max_pardons_pct: float | None = None


def _resolve_workers(value: int | str | None) -> int | None:
    """Resolve a workers value to an int, handling "auto" and validating range.

    Args:
        value: An integer, the string "auto", or None.

    Returns:
        Resolved integer worker count, or None if value is None.

    Raises:
        ValueError: If value is a non-"auto" string or a non-positive integer.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(  # noqa: TRY004 — config validation uses ValueError consistently
            f'Invalid workers value {value!r}. '
            f'Use a positive integer (e.g. workers = 4) or "auto" to match your CPU count.'
        )
    if isinstance(value, str):
        if value == 'auto':
            return os.cpu_count() or 4
        raise ValueError(
            f'Invalid workers value {value!r}. '
            f'Use a positive integer (e.g. workers = 4) or "auto" to match your CPU count.'
        )
    if not isinstance(value, int):
        raise ValueError(  # noqa: TRY004 — config validation uses ValueError consistently
            f'Invalid workers value {value!r}. '
            f'Use a positive integer (e.g. workers = 4) or "auto" to match your CPU count.'
        )
    if value <= 0:
        raise ValueError(
            f'Invalid workers value {value!r}. '
            f'Use a positive integer (e.g. workers = 4) or "auto" to match your CPU count.'
        )
    return value


def load_config(rootdir: Path) -> GremlinConfig:  # noqa: C901
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

    try:
        with pyproject_path.open('rb') as f:
            pyproject_content = tomllib.load(f)
    except TOMLDecodeError:
        logger.warning('Skipping gremlin config: malformed TOML in %s', pyproject_path)
        return GremlinConfig()

    tool_config = pyproject_content.get('tool', {}).get('pytest-gremlins', {})

    workers_raw = tool_config.get('workers')
    try:
        _resolve_workers(workers_raw)  # validate early; "auto" stays as str, resolved lazily in merge_configs
    except ValueError:
        logger.warning('Invalid workers in %s: got %r', pyproject_path, workers_raw)
        raise

    batch_size_raw = tool_config.get('batch_size')
    if batch_size_raw is not None and (not isinstance(batch_size_raw, int) or isinstance(batch_size_raw, bool)):
        logger.warning('Invalid batch_size in %s: expected positive integer, got %r', pyproject_path, batch_size_raw)
        raise ValueError(
            f'[tool.pytest-gremlins].batch_size must be a positive integer (e.g. batch_size = 50), '
            f'got {batch_size_raw!r}'
        )
    if isinstance(batch_size_raw, int) and not isinstance(batch_size_raw, bool) and batch_size_raw <= 0:
        logger.warning('Invalid batch_size in %s: expected positive integer, got %r', pyproject_path, batch_size_raw)
        raise ValueError(
            f'[tool.pytest-gremlins].batch_size must be a positive integer (e.g. batch_size = 50), '
            f'got {batch_size_raw!r}'
        )

    cache_raw = tool_config.get('cache')
    if cache_raw is not None and not isinstance(cache_raw, bool):
        logger.warning('Invalid cache in %s: expected boolean, got %r', pyproject_path, cache_raw)
        raise ValueError(f'[tool.pytest-gremlins].cache must be a boolean (e.g. cache = true), got {cache_raw!r}')

    report_raw = tool_config.get('report')
    if report_raw is not None and not isinstance(report_raw, str):
        logger.warning('Invalid report in %s: expected string, got %r', pyproject_path, report_raw)
        raise ValueError(f'[tool.pytest-gremlins].report must be a string (e.g. report = "html"), got {report_raw!r}')

    max_pardons_pct_raw = tool_config.get('max-pardons-pct')
    if max_pardons_pct_raw is not None:
        if isinstance(max_pardons_pct_raw, bool) or not isinstance(max_pardons_pct_raw, (int, float)):
            logger.warning(
                'Invalid max-pardons-pct in %s: expected float in [0, 100], got %r',
                pyproject_path,
                max_pardons_pct_raw,
            )
            raise ValueError(
                f'[tool.pytest-gremlins].max-pardons-pct must be a number between 0 and 100 '
                f'(e.g. max-pardons-pct = 5.0), got {max_pardons_pct_raw!r}'
            )
        if not (0 <= max_pardons_pct_raw <= 100):  # noqa: PLR2004
            logger.warning(
                'Invalid max-pardons-pct in %s: expected float in [0, 100], got %r',
                pyproject_path,
                max_pardons_pct_raw,
            )
            raise ValueError(
                f'[tool.pytest-gremlins].max-pardons-pct must be between 0 and 100 '
                f'(e.g. max-pardons-pct = 5.0), got {max_pardons_pct_raw!r}'
            )

    return GremlinConfig(
        operators=tool_config.get('operators'),
        paths=tool_config.get('paths'),
        exclude=tool_config.get('exclude'),
        workers=workers_raw,
        cache=cache_raw,
        report=report_raw,
        batch_size=batch_size_raw,
        max_pardons_pct=max_pardons_pct_raw,
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
            pyproject_content = tomllib.load(f)
    except TOMLDecodeError:
        logger.warning('Skipping source path discovery: malformed TOML in %s', pyproject_path)
        return []

    setuptools_config = pyproject_content.get('tool', {}).get('setuptools', {})
    if not setuptools_config:
        return []

    candidates = _collect_setuptools_candidates(setuptools_config)

    seen: set[str] = set()
    validated_paths: list[str] = []
    for candidate in candidates:
        if candidate not in seen and (rootdir / candidate).is_dir():
            seen.add(candidate)
            validated_paths.append(candidate)

    return validated_paths


def merge_configs(
    file_config: GremlinConfig,
    cli_operators: str | None = None,
    cli_targets: str | None = None,
    cli_workers: int | None = None,
    cli_cache: bool | None = None,
    cli_report: str | None = None,
    cli_batch_size: int | None = None,
    cli_max_pardons_pct: float | None = None,
) -> GremlinConfig:
    """Merge CLI arguments with file configuration.

    CLI arguments take precedence over pyproject.toml configuration.
    Empty strings are treated as not provided.

    Args:
        file_config: Configuration loaded from pyproject.toml.
        cli_operators: Comma-separated operator names from CLI (--gremlin-operators).
        cli_targets: Comma-separated target paths from CLI (--gremlin-targets).
        cli_workers: Worker count from CLI (--gremlin-workers), already resolved to int.
        cli_cache: Cache flag from CLI (--gremlin-cache).
        cli_report: Report format from CLI (--gremlin-report).
        cli_batch_size: Batch size from CLI (--gremlin-batch-size).
        cli_max_pardons_pct: Max pardoned % from CLI (--gremlin-max-pardons-pct).

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

    workers: int | None = cli_workers if cli_workers is not None else _resolve_workers(file_config.workers)
    cache: bool | None = cli_cache if cli_cache is not None else file_config.cache
    report: str | None = cli_report if cli_report is not None else file_config.report
    batch_size: int | None = cli_batch_size if cli_batch_size is not None else file_config.batch_size
    max_pardons_pct: float | None = (
        cli_max_pardons_pct if cli_max_pardons_pct is not None else file_config.max_pardons_pct
    )

    return GremlinConfig(
        operators=operators,
        paths=paths,
        exclude=file_config.exclude,
        workers=workers,
        cache=cache,
        report=report,
        batch_size=batch_size,
        max_pardons_pct=max_pardons_pct,
    )
