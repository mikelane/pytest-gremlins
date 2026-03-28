"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

import argparse
import ast
import collections.abc
from concurrent.futures import as_completed
import contextlib
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
import functools
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import (
    TYPE_CHECKING,
    Protocol,
)
import warnings

import coverage
import pytest

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.types import CachedGremlinResult
from pytest_gremlins.config import (
    VALID_REPORT_FORMATS,
    GremlinConfig,
    discover_by_importlib_metadata,
    discover_by_project_name,
    discover_by_setup_cfg,
    discover_source_paths,
    load_config,
    merge_configs,
)
from pytest_gremlins.coverage import (
    CoverageCollector,
    PrioritizedSelector,
    TestSelector,
)
from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.instrumentation.transformer import (
    get_default_registry,
    transform_source,
)
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.batch_executor import BatchExecutor
from pytest_gremlins.parallel.fork_executor import ForkExecutor
from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor
from pytest_gremlins.parallel.lightweight import build_lightweight_command
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.reporting.html import (
    HtmlReporter,
    resolve_html_output_path,
)
from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.operators import GremlinOperator


_XDIST_AVAILABLE = importlib.util.find_spec('xdist') is not None


class _XdistWorkerNode(Protocol):
    """Structural type for an xdist worker node that exposes ``workerinput``."""

    workerinput: dict[str, object]


logger = logging.getLogger(__name__)

GREMLIN_SOURCES_ENV_VAR = 'PYTEST_GREMLINS_SOURCES_FILE'


def _get_rootdir(config: pytest.Config) -> Path:
    """Return the rootdir of the pytest session as a Path.

    pytest.Config.rootdir is not part of the public typed API,
    so we centralise the single type: ignore here.
    """
    return Path(config.rootdir)  # type: ignore[attr-defined]


class CoverageMode(Enum):
    """Coverage collection strategy for mutation testing.

    Attributes:
        PIGGYBACK: Reuse pytest-cov's coverage data (``--cov`` is active).
            No separate pre-scan subprocess; tests run once.
        PRIVATE: Run gremlins' own inline coverage collection.
            No ``--cov`` in the session; no ``.coverage`` file created in rootdir.
    """

    PIGGYBACK = 'piggyback'
    PRIVATE = 'private'


def _detect_coverage_mode(config: pytest.Config) -> CoverageMode:
    """Determine which coverage collection strategy to use.

    Returns PIGGYBACK when pytest-cov's ``_cov`` plugin is registered (i.e.
    the user passed ``--cov``).  Returns PRIVATE otherwise so that gremlins
    manages its own inline coverage without touching ``rootdir/.coverage``.

    Args:
        config: The pytest config object.

    Returns:
        ``CoverageMode.PIGGYBACK`` if ``--cov`` is active, else ``CoverageMode.PRIVATE``.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> config = MagicMock()
        >>> config.pluginmanager.get_plugin.return_value = None
        >>> _detect_coverage_mode(config)
        <CoverageMode.PRIVATE: 'private'>
    """
    cov_plugin = config.pluginmanager.get_plugin('_cov')
    if cov_plugin is not None:
        return CoverageMode.PIGGYBACK
    return CoverageMode.PRIVATE


@dataclass
class GremlinSession:
    """Session state for mutation testing.

    Attributes:
        enabled: Whether mutation testing is enabled.
        operators: List of operators to use for mutation.
        report_formats: List of report formats (console, html, json).
        gremlins: All gremlins found in the source code.
        results: Results from testing each gremlin.
        source_files: Mapping of file paths to their source code.
        test_files: List of test file paths that were collected.
        instrumented_dir: Temporary directory containing instrumented source files.
        coverage_collector: Collects coverage data per-test.
        test_selector: Selects tests based on coverage data.
        prioritized_selector: Selects tests ordered by specificity (most specific first).
        test_node_ids: Maps test names to their pytest node IDs.
        total_tests: Total number of tests collected.
        cache_enabled: Whether incremental caching is enabled.
        cache: The incremental cache instance (if caching is enabled).
        source_hashes: Content hashes for source files.
        test_hashes: Content hashes for test files.
        cache_hits: Number of cache hits in this session.
        cache_misses: Number of cache misses in this session.
        parallel_enabled: Whether parallel execution is enabled.
        parallel_workers: Number of parallel workers (None = CPU count).
        batch_enabled: Whether batch execution mode is enabled.
        batch_size: Number of gremlins per batch in batch mode.
        xdist_item_ids: Test node IDs captured from the first xdist worker after
            collection finishes.  ``None`` until the hook fires; ``[]`` if the
            worker collected nothing.
        coverage_mode: Whether to reuse pytest-cov's coverage (PIGGYBACK) or
            manage an inline coverage instance (PRIVATE).
        private_coverage: The inline ``coverage.Coverage`` instance used in
            PRIVATE mode.  ``None`` in PIGGYBACK mode or before session start.
        gremlins_tmpdir: Path (as a string) to the shared temporary directory
            where xdist workers write their per-worker coverage data files in
            PRIVATE mode.  ``None`` when xdist is not active.
        exclude_patterns: Glob patterns from ``[tool.pytest-gremlins] exclude``
            used to skip matching files during source discovery.
    """

    enabled: bool = False
    operators: list[GremlinOperator] = field(default_factory=list)
    report_formats: list[str] = field(default_factory=lambda: ['console'])
    gremlins: list[Gremlin] = field(default_factory=list)
    results: list[GremlinResult] = field(default_factory=list)
    source_files: dict[str, str] = field(default_factory=dict)
    test_files: list[Path] = field(default_factory=list)
    target_paths: list[Path] = field(default_factory=list)
    instrumented_dir: Path | None = None
    coverage_collector: CoverageCollector | None = None
    test_selector: TestSelector | None = None
    prioritized_selector: PrioritizedSelector | None = None
    test_node_ids: dict[str, str] = field(default_factory=dict)
    total_tests: int = 0
    cache_enabled: bool = False
    cache: IncrementalCache | None = None
    source_hashes: dict[str, str] = field(default_factory=dict)
    test_hashes: dict[str, str] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0
    parallel_enabled: bool = False
    parallel_workers: int | None = None
    batch_enabled: bool = False
    batch_size: int = 10
    xdist_item_ids: list[str] | None = None
    xdist_active: bool = False
    xdist_workers: int | None = None
    coverage_mode: CoverageMode = CoverageMode.PRIVATE
    private_coverage: coverage.Coverage | None = None
    gremlins_tmpdir: str | None = None
    exclude_patterns: list[str] = field(default_factory=list)
    strict_pardons: bool = False
    audit_pardons: bool = False
    max_pardons_pct: float | None = None
    max_pardons: int | None = None


_gremlin_session: GremlinSession | None = None


def _extract_test_name_from_context(context: str) -> str:
    """Extract the test function name from a coverage dynamic context string.

    Handles two context formats:

    - **New format** (GremlinContextPlugin): ``{nodeid}|{when}``
      e.g. ``tests/test_foo.py::TestClass::test_bar|run``
      The nodeid part is everything before ``|``; the function name is the
      last ``::``-separated segment of the nodeid.

    - **Old format** (coverage dynamic_context=test_function):
      e.g. ``test_bar`` or ``TestClass.test_method`` or ``path::test_func``
      The function name is the last ``::`` or ``.``-separated segment.

    Args:
        context: The raw context string from the coverage database.

    Returns:
        The test function name extracted from the context.

    Examples:
        >>> _extract_test_name_from_context('tests/test_foo.py::test_bar|run')
        'test_bar'
        >>> _extract_test_name_from_context('tests/test_foo.py::test_bar|setup')
        'test_bar'
        >>> _extract_test_name_from_context('tests/test_foo.py::TestFoo::test_bar|run')
        'test_bar'
        >>> _extract_test_name_from_context('test_bar')
        'test_bar'
        >>> _extract_test_name_from_context('TestClass.test_method')
        'test_method'
        >>> _extract_test_name_from_context('tests/test_foo.py::test_func')
        'test_func'
    """
    if '|' in context:
        nodeid = context.split('|', maxsplit=1)[0]
        return nodeid.split('::')[-1] if '::' in nodeid else nodeid
    if '::' in context:
        return context.rsplit('::', maxsplit=1)[-1]
    return context.rsplit('.', maxsplit=1)[-1]


def _is_xdist_worker(config: pytest.Config) -> bool:
    """Return True if this process is an xdist worker node.

    xdist workers have a ``workerinput`` attribute on the config object that
    the controller uses to pass per-worker configuration.  Controllers and
    plain (non-xdist) sessions do not have this attribute.

    Args:
        config: The pytest config object.

    Returns:
        True when running inside an xdist worker process, False otherwise.

    Examples:
        >>> import pytest
        >>> from unittest.mock import MagicMock
        >>> worker_config = MagicMock(spec=['workerinput'])
        >>> _is_xdist_worker(worker_config)
        True
        >>> plain_config = MagicMock(spec=[])
        >>> _is_xdist_worker(plain_config)
        False
    """
    return hasattr(config, 'workerinput')


def _read_parallel_config(config: pytest.Config, xdist_workers: int | None = None) -> tuple[bool, int | None]:
    """Determine parallel_enabled and parallel_workers from config options.

    Reads ``--gremlin-parallel`` and ``--gremlin-workers`` from the config
    options.  When neither is set and xdist was active, falls back to using
    the xdist worker count as the default parallel worker count.

    Args:
        config: The pytest config object after option parsing.
        xdist_workers: Resolved integer worker count from xdist ``-n`` flag,
            or None if xdist is not active.  Callers must convert ``'auto'``
            to None before passing (``ProcessPoolExecutor`` rejects strings).
            Used as a fallback when ``--gremlin-workers`` is not explicitly set.

    Returns:
        A tuple of (parallel_enabled, parallel_workers).
    """
    cli_workers: int | None = config.option.gremlin_workers
    if cli_workers is None and xdist_workers is not None:
        return True, xdist_workers
    parallel_enabled: bool = config.option.gremlin_parallel or cli_workers is not None
    return parallel_enabled, cli_workers


def _get_session() -> GremlinSession | None:
    """Get the current gremlin session."""
    return _gremlin_session


def _set_session(session: GremlinSession | None) -> None:
    """Set the current gremlin session."""
    global _gremlin_session  # noqa: PLW0603
    _gremlin_session = session


def _workers_type(value: str) -> int:
    """Parse the --gremlin-workers argument, accepting 'auto' or a positive integer.

    Args:
        value: The raw string value from the CLI.

    Returns:
        The number of workers as an integer.

    Raises:
        argparse.ArgumentTypeError: When value is not 'auto' or a valid integer.
    """
    if value == 'auto':
        return os.cpu_count() or 4
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'Invalid workers value: {value!r}') from exc
    if workers <= 0:
        raise argparse.ArgumentTypeError(f'Workers must be a positive integer, got {value!r}')
    return workers


def _parse_cli_report_formats(raw: str | list[str] | None) -> list[str] | None:
    """Parse raw --gremlin-report CLI value into a validated format list.

    Handles both a single comma-separated string and a list of strings
    (from ``action='append'``).  Joins all elements, splits on commas,
    strips whitespace, filters empties, and deduplicates while preserving
    insertion order.

    Args:
        raw: The raw value from ``config.option.gremlin_report``.
            ``None`` when the flag was not passed, a ``list[str]`` when
            passed one or more times via ``action='append'``.

    Returns:
        Deduplicated list of format strings, or ``None`` if *raw* is ``None``.

    Raises:
        SystemExit: Via ``pytest.exit`` when the value is empty after
            filtering or contains unknown formats.
    """
    if raw is None:
        return None

    joined = ','.join(raw) if isinstance(raw, list) else raw
    formats = list(dict.fromkeys(fmt.strip() for fmt in joined.split(',') if fmt.strip()))

    if not formats:
        pytest.exit(
            f'--gremlin-report must contain at least one valid format. Valid: {sorted(VALID_REPORT_FORMATS)}',
            returncode=4,
        )

    invalid = set(formats) - VALID_REPORT_FORMATS
    if invalid:
        pytest.exit(
            f'Unknown --gremlin-report format(s): {sorted(invalid)}. Valid: {sorted(VALID_REPORT_FORMATS)}',
            returncode=4,
        )

    return formats


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command-line options for pytest-gremlins."""
    group = parser.getgroup('gremlins', 'mutation testing with gremlins')
    group.addoption(
        '--gremlins',
        action='store_true',
        default=False,
        dest='gremlins',
        help='Enable mutation testing (feed the gremlins after midnight)',
    )
    group.addoption(
        '--gremlin-operators',
        action='store',
        default=None,
        dest='gremlin_operators',
        help='Comma-separated list of mutation operators to use',
    )
    group.addoption(
        '--gremlin-report',
        action='append',
        default=None,
        dest='gremlin_report',
        help='Report format(s), comma-separated: console, html, json (default: console)',
    )
    group.addoption(
        '--gremlin-targets',
        action='store',
        default=None,
        dest='gremlin_targets',
        help='Comma-separated list of source directories/files to mutate',
    )
    group.addoption(
        '--gremlin-exclude',
        action='append',
        default=None,
        dest='gremlin_exclude',
        help='Glob pattern to exclude from mutation (repeatable, overrides pyproject.toml)',
    )
    group.addoption(
        '--gremlin-cache',
        action='store_true',
        default=False,
        dest='gremlin_cache',
        help='Enable incremental analysis cache (skip unchanged code)',
    )
    group.addoption(
        '--gremlin-clear-cache',
        action='store_true',
        default=False,
        dest='gremlin_clear_cache',
        help='Clear the incremental analysis cache before running',
    )
    group.addoption(
        '--gremlin-parallel',
        action='store_true',
        default=False,
        dest='gremlin_parallel',
        help='Enable parallel gremlin execution across multiple workers',
    )
    group.addoption(
        '--gremlin-workers',
        action='store',
        type=_workers_type,
        default=None,
        dest='gremlin_workers',
        help='Number of parallel workers; implies --gremlin-parallel (default: CPU count)',
    )
    group.addoption(
        '--gremlin-batch',
        action='store_true',
        default=False,
        dest='gremlin_batch',
        help='Enable batch execution to reduce subprocess overhead',
    )
    group.addoption(
        '--gremlin-batch-size',
        action='store',
        type=int,
        default=None,
        dest='gremlin_batch_size',
        help='Number of gremlins per batch (default: 10)',
    )
    group.addoption(
        '--gremlins-html-dir',
        action='store',
        default=None,
        dest='gremlins_html_dir',
        help='Custom output directory for the HTML report (default: coverage/gremlins/)',
    )
    group.addoption(
        '--strict-pardons',
        action='store_true',
        default=False,
        dest='strict_pardons',
        help='Treat pardoned gremlins as CI failures',
    )
    group.addoption(
        '--gremlin-audit-pardons',
        action='store_true',
        default=False,
        dest='gremlin_audit_pardons',
        help='List all active suppression pragmas with location, reason, and justification',
    )
    group.addoption(
        '--gremlin-max-pardons-pct',
        action='store',
        type=float,
        default=None,
        dest='gremlin_max_pardons_pct',
        help='Fail if pardoned (pragma-suppressed) gremlins exceed this %% of total (default: disabled)',
    )
    group.addoption(
        '--max-pardons',
        action='store',
        type=int,
        default=None,
        dest='max_pardons',
        help='Fail if absolute pardoned gremlin count exceeds N (default: disabled)',
    )
    group.addoption(
        '--gremlin-executor',
        default='subprocess',
        choices=['subprocess', 'fork', 'inprocess'],
        dest='gremlin_executor',
        help='Execution strategy: subprocess (default), fork (faster, Unix), inprocess (fastest, no isolation).',
    )


def _init_cache(
    rootdir: Path,
    cache_enabled: bool,
    clear_cache: bool,
) -> IncrementalCache | None:
    """Initialise the incremental cache when enabled, optionally clearing it first.

    Args:
        rootdir: Project root directory where the cache directory is created.
        cache_enabled: Whether to create a cache instance at all.
        clear_cache: Whether to wipe the cache before use.

    Returns:
        An open IncrementalCache, or None when caching is disabled.
    """
    if not cache_enabled:
        return None
    cache_dir = rootdir / '.gremlins_cache'
    cache = IncrementalCache(cache_dir)
    if clear_cache:
        cache.clear()
        print('pytest-gremlins: cache cleared')
    return cache


def _extract_toml_fields(
    merged_config: object,
) -> tuple[bool | None, int | str | None, list[str] | None, int | None, float | None, int | None]:
    """Extract merged-config fields, guarding against test mock objects.

    Returns (cache, workers, report_formats, batch_size, max_pardons_pct, max_pardons) from
    merged_config only when it is a real GremlinConfig instance; otherwise returns
    all-None so pytest_configure falls back to argparse defaults.

    Args:
        merged_config: The result of merge_configs (GremlinConfig or a test mock).

    Returns:
        Tuple of (cache, workers, report, batch_size, max_pardons_pct, max_pardons),
        each None if unset.
    """
    if not isinstance(merged_config, GremlinConfig):
        return None, None, None, None, None, None
    return (
        merged_config.cache,
        merged_config.workers,
        merged_config.report,
        merged_config.batch_size,
        merged_config.max_pardons_pct,
        merged_config.max_pardons,
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options.

    Configuration precedence (highest to lowest):
    1. CLI arguments (--gremlin-operators, --gremlin-targets, --gremlin-exclude,
       --gremlin-workers, --gremlin-report, --gremlin-batch-size, --gremlin-cache)
    2. pyproject.toml [tool.pytest-gremlins] section
    3. Built-in defaults (all operators, src/ directory, console report, batch-size 10)
    """
    if not config.option.gremlins:
        _set_session(GremlinSession(enabled=False))
        return

    # xdist with -n > 0 distributes test items across workers; gremlins runs
    # its mutation phase sequentially after xdist tears down (two-phase mode).
    # -n 0 means "no distribution" — treat it the same as xdist not present.
    xdist_numprocesses = getattr(config.option, 'numprocesses', None)
    xdist_active = xdist_numprocesses not in (None, 0)

    rootdir = _get_rootdir(config)

    cli_max_pardons_pct: float | None = getattr(config.option, 'gremlin_max_pardons_pct', None)
    if cli_max_pardons_pct is not None and not (0 <= cli_max_pardons_pct <= 100):  # noqa: PLR2004
        pytest.exit(
            f'--gremlin-max-pardons-pct must be between 0 and 100, got {cli_max_pardons_pct!r}.',
            returncode=4,
        )

    cli_max_pardons: int | None = getattr(config.option, 'max_pardons', None)
    if cli_max_pardons is not None and cli_max_pardons < 0:
        pytest.exit(
            f'--max-pardons must be >= 0, got {cli_max_pardons!r}.',
            returncode=4,
        )

    cli_report_list = _parse_cli_report_formats(config.option.gremlin_report)

    # Load config from pyproject.toml and merge with CLI args
    file_config = load_config(rootdir)
    merged_config = merge_configs(
        file_config,
        cli_operators=config.option.gremlin_operators,
        cli_targets=config.option.gremlin_targets,
        cli_exclude=config.option.gremlin_exclude,
        cli_workers=config.option.gremlin_workers,
        cli_cache=config.option.gremlin_cache or None,
        cli_report=cli_report_list,
        cli_batch_size=config.option.gremlin_batch_size,
        cli_max_pardons_pct=cli_max_pardons_pct,
        cli_max_pardons=cli_max_pardons,
    )

    registry = get_default_registry()

    # Use merged operators or all if none specified
    operators = registry.get_all(enabled=merged_config.operators) if merged_config.operators else registry.get_all()

    # Use merged paths, then try setuptools discovery, then fall back to src/
    target_paths: list[Path] = []
    if merged_config.paths:
        for path_str in merged_config.paths:
            path = rootdir / path_str if not Path(path_str).is_absolute() else Path(path_str)
            if path.exists():
                target_paths.append(path)
    else:
        discovered = (
            discover_source_paths(rootdir)
            or discover_by_project_name(rootdir)
            or discover_by_setup_cfg(rootdir)
            or discover_by_importlib_metadata(rootdir)
        )
        if discovered:
            target_paths.extend(rootdir / p for p in discovered)
        else:
            src_path = rootdir / 'src'
            if src_path.exists():
                target_paths.append(src_path)
            else:
                logger.warning(
                    'No source paths discovered; scanning the entire project root (%s). '
                    'This may be slower and include files you did not intend to mutate. '
                    'Add paths to pyproject.toml to target only your source code:\n'
                    '  [tool.pytest-gremlins]\n'
                    '  paths = ["src/your_package"]',
                    rootdir,
                )
                target_paths.append(rootdir)

    (
        toml_cache,
        toml_workers,
        toml_report,
        toml_batch_size,
        toml_max_pardons_pct,
        toml_max_pardons,
    ) = _extract_toml_fields(merged_config)

    # Cache: merge_configs already resolved CLI-beats-TOML; default False
    cache_enabled: bool = bool(toml_cache)
    cache: IncrementalCache | None = _init_cache(rootdir, cache_enabled, config.option.gremlin_clear_cache)

    xdist_worker_int: int | None = xdist_numprocesses if isinstance(xdist_numprocesses, int) else None
    xdist_workers_for_parallel = xdist_worker_int if xdist_active else None
    parallel_enabled, parallel_workers = _read_parallel_config(config, xdist_workers=xdist_workers_for_parallel)
    merged_workers = toml_workers if isinstance(toml_workers, int) else None
    if parallel_workers is None and merged_workers is not None:
        parallel_workers = merged_workers
        parallel_enabled = True

    # Batch and report: merge_configs already resolved CLI-beats-TOML
    batch_enabled = config.option.gremlin_batch
    batch_size: int = toml_batch_size if toml_batch_size is not None else 10
    report_formats: list[str] = toml_report if toml_report is not None else ['console']

    _set_session(
        GremlinSession(
            enabled=True,
            operators=operators,
            report_formats=report_formats,
            target_paths=target_paths,
            exclude_patterns=(merged_config.exclude or []) if isinstance(merged_config, GremlinConfig) else [],
            cache_enabled=cache_enabled,
            cache=cache,
            parallel_enabled=parallel_enabled,
            parallel_workers=parallel_workers,
            batch_enabled=batch_enabled,
            batch_size=batch_size,
            coverage_mode=_detect_coverage_mode(config),
            strict_pardons=bool(config.option.strict_pardons),
            audit_pardons=bool(config.option.gremlin_audit_pardons),
            max_pardons_pct=toml_max_pardons_pct,
            max_pardons=toml_max_pardons,
            xdist_active=xdist_active,
            xdist_workers=xdist_worker_int if xdist_active else None,
        )
    )


if _XDIST_AVAILABLE:

    def pytest_configure_node(node: _XdistWorkerNode) -> None:
        """Inject gremlins tmpdir into xdist worker input for PRIVATE coverage mode.

        Called on the controller for each xdist worker node before it starts.
        Injects ``gremlins_tmpdir`` so workers can write their coverage data to a
        shared directory that the controller combines in ``pytest_sessionfinish``.

        Only active in PRIVATE mode; PIGGYBACK mode relies on pytest-cov's own
        xdist integration for coverage combining.

        Args:
            node: The xdist worker node object.  Must have a ``workerinput`` dict.
        """
        gremlin_session = _get_session()
        if gremlin_session is None or not gremlin_session.enabled:
            return

        if gremlin_session.coverage_mode != CoverageMode.PRIVATE:
            return

        if gremlin_session.gremlins_tmpdir is None:  # pragma: no cover
            logger.warning(
                'pytest_configure_node: gremlins_tmpdir is None in PRIVATE mode; '
                'worker coverage data will not be combined'
            )
            return

        node.workerinput['gremlins_tmpdir'] = gremlin_session.gremlins_tmpdir
        logger.debug('pytest_configure_node: injected gremlins_tmpdir=%s', gremlin_session.gremlins_tmpdir)


def pytest_sessionstart(session: pytest.Session) -> None:
    """At session start, register GremlinContextPlugin for coverage context tracking.

    In PIGGYBACK mode (``--cov`` is active), attaches a
    :class:`~pytest_gremlins.coverage.context_plugin.GremlinContextPlugin`
    to the pytest-cov coverage instance so that every test phase is tagged
    with ``{nodeid}|{when}`` in the coverage database.

    In PRIVATE mode, creates a fresh ``coverage.Coverage`` instance, stores it
    on the session, and registers a ``GremlinContextPlugin`` on it.  The
    coverage instance is started/stopped in ``pytest_runtestloop``.

    Args:
        session: The pytest session object.
    """
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if gremlin_session.coverage_mode == CoverageMode.PIGGYBACK:
        cov_plugin = session.config.pluginmanager.get_plugin('_cov')
        if cov_plugin is None or cov_plugin.cov_controller is None:
            return
        cov_instance = cov_plugin.cov_controller.cov
        context_plugin = GremlinContextPlugin(cov_instance)
        session.config.pluginmanager.register(context_plugin)
    else:
        private_cov = coverage.Coverage(data_suffix=True)
        gremlin_session.private_coverage = private_cov
        context_plugin = GremlinContextPlugin(private_cov)
        session.config.pluginmanager.register(context_plugin)


if _XDIST_AVAILABLE:

    def pytest_xdist_node_collection_finished(node: object, ids: list[str]) -> None:  # noqa: ARG001
        """Capture item IDs reported by the first xdist worker after it finishes collection.

        xdist workers each collect all test items independently and report them
        via this hook.  All workers collect identically, so we only store the
        first worker's list and ignore subsequent calls.

        Args:
            node: The xdist worker node (unused; all workers collect the same items).
            ids: The list of test node IDs collected by this worker.
        """
        gremlin_session = _get_session()
        if gremlin_session is None or not gremlin_session.enabled:
            return

        if gremlin_session.xdist_item_ids is not None:
            return

        gremlin_session.xdist_item_ids = list(ids)
        if not ids:
            logger.warning(
                'pytest_xdist_node_collection_finished: first worker reported zero collected items; '
                'Phase 2 gremlin generation will have no tests to run against'
            )
        else:
            logger.debug('pytest_xdist_node_collection_finished: captured %d item IDs from first worker', len(ids))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtestloop(session: pytest.Session) -> collections.abc.Generator[None, None, None]:  # noqa: ARG001
    """Start and stop private coverage around the full test loop.

    In PRIVATE mode, wraps the entire test run so coverage is active for all
    tests.  After the test loop finishes, stops and saves the coverage data for
    later reading in ``pytest_sessionfinish``.

    In PIGGYBACK mode or when gremlins is disabled, this hook is transparent.

    Args:
        session: The pytest session (unused; coverage instance is on GremlinSession).

    Yields:
        Control to the next hook implementation (the actual test runner).
    """
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled or gremlin_session.private_coverage is None:
        yield
        return

    private_cov = gremlin_session.private_coverage
    private_cov.start()
    yield
    private_cov.stop()
    private_cov.save()


def pytest_collection_finish(session: pytest.Session) -> None:
    """After test collection, discover source files and generate gremlins.

    In xdist mode the controller has zero items; this hook records test files
    and normalises node IDs but skips gremlin generation — that happens in
    ``pytest_sessionfinish`` once worker item IDs are available.
    """
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if _is_xdist_worker(session.config):
        return

    test_files = [Path(item.fspath) for item in session.items if hasattr(item, 'fspath')]
    gremlin_session.test_files = list(set(test_files))

    gremlin_session.total_tests = len(session.items)

    # Normalize node IDs for subprocess execution.
    # In some contexts (e.g. pytester) node IDs can include absolute paths, and
    # some plugins (e.g. pytest-test-categories) add display suffixes like
    # "[SMALL]" which are not valid when passed back to pytest.
    rootdir = _get_rootdir(session.config)
    node_ids = [item.nodeid for item in session.items]
    normalized_node_ids = _make_node_ids_relative(node_ids, rootdir)
    gremlin_session.test_node_ids = {
        item.name: node_id for item, node_id in zip(session.items, normalized_node_ids, strict=True)
    }

    source_files = _discover_source_files(session, gremlin_session)
    gremlin_session.source_files = source_files

    # Compute content hashes for source and test files (for caching)
    if gremlin_session.cache_enabled:
        hasher = ContentHasher()
        for file_path, source in source_files.items():
            gremlin_session.source_hashes[file_path] = hasher.hash_string(source)
        for test_file in gremlin_session.test_files:
            with contextlib.suppress(FileNotFoundError):
                gremlin_session.test_hashes[str(test_file)] = hasher.hash_file(test_file)

    if gremlin_session.xdist_active and not session.items:
        logger.debug(
            'pytest_collection_finish: xdist controller has zero items; '
            'deferring gremlin generation to pytest_sessionfinish'
        )
        return

    _generate_gremlins(gremlin_session, source_files, rootdir)


def _generate_gremlins(
    gremlin_session: GremlinSession,
    source_files: dict[str, str],
    rootdir: Path,
) -> None:
    """Generate gremlins from source files and write instrumented sources.

    Transforms each source file into a set of gremlins and an instrumented AST,
    stores the gremlins on the session, and writes the instrumented sources to a
    temporary directory for use during mutation testing.

    Args:
        gremlin_session: The current gremlin session.
        source_files: Mapping of file paths to their source code.
        rootdir: Root directory of the project.
    """
    all_gremlins: list[Gremlin] = []
    instrumented_asts: dict[str, ast.Module] = {}

    for file_path, source in source_files.items():
        try:
            gremlins, instrumented_tree = transform_source(source, file_path, gremlin_session.operators)
        except Exception:
            logger.exception('Failed to transform %s; skipping file', file_path)
            continue
        all_gremlins.extend(gremlins)
        instrumented_asts[file_path] = instrumented_tree

    gremlin_session.gremlins = all_gremlins

    if all_gremlins:
        instrumented_dir = _write_instrumented_sources(instrumented_asts, rootdir)
        gremlin_session.instrumented_dir = instrumented_dir


def _discover_source_files(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> dict[str, str]:
    """Discover Python source files to mutate.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        Dictionary mapping file paths to their source code.
    """
    source_files: dict[str, str] = {}
    rootdir = _get_rootdir(session.config)

    exclude_patterns = gremlin_session.exclude_patterns

    for target_path in gremlin_session.target_paths:
        resolved_path = target_path if target_path.is_absolute() else rootdir / target_path

        if resolved_path.is_file() and resolved_path.suffix == '.py':
            if not _is_excluded(resolved_path, rootdir, exclude_patterns):
                _add_source_file(resolved_path, source_files)
        elif resolved_path.is_dir():
            for py_file in resolved_path.rglob('*.py'):
                if _should_include_file(py_file) and not _is_excluded(py_file, rootdir, exclude_patterns):
                    _add_source_file(py_file, source_files)

    return source_files


@functools.lru_cache(maxsize=256)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern to a compiled regex with proper ``**`` support.

    ``fnmatch.fnmatch`` treats ``**`` the same as ``*`` and cannot match zero
    intermediate directories.  This helper splits on ``/`` and emits a regex
    where ``**`` correctly matches zero or more path segments.

    - ``**``  at the start  → ``(?:.+/)?``  (zero-or-more dirs with trailing ``/``)
    - ``**``  in the middle → ``(?:/.+)?/``  (zero-or-more dirs between separators)
    - ``**``  at the end    → ``(?:/.*)?``   (anything remaining)
    - ``*``                 → ``[^/]*``      (anything except ``/``)
    - ``?``                 → ``[^/]``       (single char except ``/``)

    Examples:
        >>> import re
        >>> bool(_glob_to_regex('**/migrations/*').match('migrations/0001.py'))
        True
        >>> bool(_glob_to_regex('**/migrations/*').match('src/app/migrations/0001.py'))
        True
        >>> bool(_glob_to_regex('src/**/migrations/*').match('src/migrations/0001.py'))
        True
    """
    pattern = pattern.replace('\\', '/')
    parts = pattern.split('/')
    regex_parts: list[str] = []

    for i, part in enumerate(parts):
        if part == '**':
            if i == 0 and i == len(parts) - 1:
                regex_parts.append('.*')
            elif i == 0:
                regex_parts.append('(?:.+/)?')
            elif i == len(parts) - 1:
                regex_parts.append('(?:/.*)?')
            else:
                regex_parts.append('(?:/.+)?/')
        else:
            if i > 0 and parts[i - 1] != '**':
                regex_parts.append('/')
            for ch in part:
                if ch == '*':
                    regex_parts.append('[^/]*')
                elif ch == '?':
                    regex_parts.append('[^/]')
                else:
                    regex_parts.append(re.escape(ch))

    return re.compile('^' + ''.join(regex_parts) + '$')


def _is_excluded(path: Path, rootdir: Path, exclude_patterns: list[str]) -> bool:
    """Check if a path matches any exclude glob pattern.

    Converts the path to a forward-slash-separated string relative to
    *rootdir*, then tests each pattern using :func:`_glob_to_regex` which
    handles ``**`` (zero-or-more directories) correctly — unlike
    ``fnmatch.fnmatch`` which treats ``**`` the same as ``*``.

    Args:
        path: Absolute path to the source file.
        rootdir: Project root directory.
        exclude_patterns: Glob patterns from the ``[tool.pytest-gremlins]``
            ``exclude`` list.

    Returns:
        True if the file matches any exclude pattern.  Returns False
        when *path* is not relative to *rootdir* (e.g. an absolute target
        pointing outside the project).

    Examples:
        >>> from pathlib import Path
        >>> _is_excluded(
        ...     Path('/p/src/app/migrations/0001.py'),
        ...     Path('/p'),
        ...     ['**/migrations/*'],
        ... )
        True
        >>> _is_excluded(Path('/p/src/app/models.py'), Path('/p'), ['**/migrations/*'])
        False
        >>> _is_excluded(
        ...     Path('/p/migrations/0001.py'),
        ...     Path('/p'),
        ...     ['**/migrations/*'],
        ... )
        True
    """
    if not exclude_patterns:
        return False
    try:
        rel_path = str(path.relative_to(rootdir)).replace('\\', '/')
    except ValueError:
        return False
    return any(_glob_to_regex(pattern).match(rel_path) is not None for pattern in exclude_patterns)


def _should_include_file(path: Path) -> bool:
    """Check if a file should be included in mutation testing.

    Args:
        path: Path to the file.

    Returns:
        True if the file should be included.
    """
    name = path.name
    if name.startswith('test_') or name.endswith('_test.py'):
        return False
    if name == 'conftest.py':
        return False
    return '__pycache__' not in str(path)


def _add_source_file(path: Path, source_files: dict[str, str]) -> None:
    """Add a source file to the collection.

    Args:
        path: Path to the source file.
        source_files: Dictionary to add the file to.
    """
    try:
        source = path.read_text()
        ast.parse(source)
        source_files[str(path)] = source
    except SyntaxError:
        logger.debug('Skipping %s: syntax error', path)
    except OSError as exc:
        logger.debug('Skipping %s: %s', path, exc)


def _write_instrumented_sources(
    instrumented_asts: dict[str, ast.Module],
    rootdir: Path,
) -> Path:
    """Write instrumented sources to a JSON file for import hook injection.

    Creates a temporary directory containing:
    1. A JSON file mapping module names to their instrumented source code
    2. A bootstrap script that registers import hooks and runs pytest

    This approach ensures that import hooks are registered BEFORE any modules
    are imported, which is necessary because pytest adds the test directory
    to sys.path before PYTHONPATH.

    Args:
        instrumented_asts: Mapping of original file paths to their instrumented ASTs.
        rootdir: Root directory of the project.

    Returns:
        Path to the temporary directory containing the bootstrap infrastructure.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix='pytest_gremlins_'))

    gremlin_active_injection = f"""import os as _gremlin_os
__gremlin_active__ = _gremlin_os.environ.get('{ACTIVE_GREMLIN_ENV_VAR}')
del _gremlin_os
"""

    injection_nodes = ast.parse(gremlin_active_injection).body

    instrumented_sources: dict[str, str] = {}
    for original_path, tree in instrumented_asts.items():
        module_name = _path_to_module_name(Path(original_path), rootdir)
        injected_body = _prepend_injection(tree.body, injection_nodes)
        instrumented_sources[module_name] = ast.unparse(ast.Module(body=injected_body, type_ignores=tree.type_ignores))

    sources_file = temp_dir / 'sources.json'
    sources_file.write_text(json.dumps(instrumented_sources))

    bootstrap_script = temp_dir / 'gremlin_bootstrap.py'
    bootstrap_script.write_text(_get_bootstrap_script())

    lightweight_runner = temp_dir / 'gremlin_lightweight_runner.py'
    lightweight_runner.write_text(_get_lightweight_runner_script())

    return temp_dir


def _prepend_injection(body: list[ast.stmt], injection_nodes: list[ast.stmt]) -> list[ast.stmt]:
    """Insert injection nodes after any module docstring and future imports.

    Python requires that ``from __future__`` imports appear before all other
    statements (except the module docstring).  Inserting the gremlin activation
    code via text concatenation before ``ast.unparse`` output violates this rule
    when the source already contains a ``from __future__`` import, causing a
    ``SyntaxError``.  This function inserts the injection at the AST level so
    the final ordering is always:

    1. Module docstring (if present)
    2. ``from __future__`` imports (if present)
    3. Injection nodes
    4. Remaining statements

    Args:
        body: The top-level statement list from an instrumented ``ast.Module``.
        injection_nodes: Parsed AST nodes for the gremlin activation code.

    Returns:
        A new statement list with injection nodes placed at the correct position.
    """
    insert_position = 0

    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        insert_position = 1

    while insert_position < len(body):
        node = body[insert_position]
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            insert_position += 1
        else:
            break

    return body[:insert_position] + injection_nodes + body[insert_position:]


def _path_to_module_name(file_path: Path, rootdir: Path) -> str:
    """Convert a file path to a Python module name.

    Args:
        file_path: Path to the Python file.
        rootdir: Root directory of the project.

    Returns:
        The module name (e.g., 'package.module' for 'package/module.py').
        For src/ layout projects, the 'src' prefix is stripped since it's
        a layout convention, not part of the import path.
    """
    try:
        relative = file_path.relative_to(rootdir)
    except ValueError:
        relative = Path(file_path.name)

    parts = list(relative.with_suffix('').parts)

    # Strip 'src' prefix for src/ layout projects.
    # Python imports use 'mypackage.module', not 'src.mypackage.module'.
    if parts and parts[0] == 'src':
        parts = parts[1:]

    return '.'.join(parts)


def _build_gremlin_module_map(
    gremlins: list[Gremlin],
    rootdir: Path,
) -> dict[str, str]:
    """Map gremlin IDs to their module names for in-process execution.

    Args:
        gremlins: List of gremlins to map.
        rootdir: Root directory of the project.

    Returns:
        Dictionary mapping gremlin IDs to dotted module names.
    """
    gremlin_module_map: dict[str, str] = {}
    for gremlin in gremlins:
        file_path = Path(gremlin.file_path)
        try:
            rel_path = file_path.relative_to(rootdir)
        except ValueError:
            rel_path = Path(file_path.name)
        module_name = str(rel_path).replace(os.sep, '.').removesuffix('.py')
        if module_name.endswith('.__init__'):
            module_name = module_name.removesuffix('.__init__')
        gremlin_module_map[gremlin.gremlin_id] = module_name
    return gremlin_module_map


def _get_bootstrap_script() -> str:
    """Return the bootstrap script that registers import hooks and runs pytest.

    The bootstrap script:
    1. Reads instrumented sources from a JSON file
    2. Registers a MetaPathFinder that intercepts imports for instrumented modules
    3. Runs pytest with any provided arguments

    Note: The use of compile() and the exec built-in here is intentional and safe.
    We are executing pre-transformed AST code from our own instrumentation process,
    not arbitrary user input. This is the standard pattern for custom import loaders.

    Returns:
        The bootstrap script source code.
    """
    # The bootstrap script uses exec() to run compiled code in module namespace.
    # This is the standard Python pattern for import loaders (see importlib docs).
    # The code being executed is our own instrumented AST, not untrusted input.
    return """#!/usr/bin/env python
'''Bootstrap script for pytest-gremlins mutation testing.

This script registers import hooks to intercept module imports and provide
instrumented code with mutation switching logic, then runs pytest.
'''

import json
import os
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec


def main():
    sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE')
    if not sources_file:
        print('Error: PYTEST_GREMLINS_SOURCES_FILE not set', file=sys.stderr)
        sys.exit(1)

    with open(sources_file) as f:
        instrumented_sources = json.load(f)

    # Get exec function - use indirect access to satisfy linters
    # This is the standard pattern for import loaders (see importlib docs)
    run_code = getattr(__builtins__, 'exec', None) or __builtins__.get('exec')

    class GremlinLoader(Loader):
        def __init__(self, source, module_name):
            self._source = source
            self._module_name = module_name

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            # Compile and execute the instrumented source in the module's namespace.
            # The code comes from our AST transformation, not untrusted input.
            code = compile(self._source, self._module_name, 'exec')
            run_code(code, module.__dict__)

    class GremlinFinder(MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname in instrumented_sources:
                loader = GremlinLoader(instrumented_sources[fullname], fullname)
                return ModuleSpec(fullname, loader)
            return None

    # Register finder at the START of meta_path
    sys.meta_path.insert(0, GremlinFinder())

    # Now run pytest with remaining arguments
    import pytest
    sys.exit(pytest.main(sys.argv[1:]))


if __name__ == '__main__':
    main()
"""


def _get_lightweight_runner_script() -> str:
    """Return a lightweight test runner that avoids full pytest startup.

    Instead of running ``pytest.main()``, this script directly imports test
    modules and calls test functions.  This eliminates ~900ms of pytest
    framework overhead per subprocess, reducing per-gremlin cost from ~950ms
    to ~50ms.

    The runner handles class-based tests (``TestFoo::test_bar``) and
    function-based tests (``test_bar``), with ``-x`` semantics (stop on
    first failure).  Exit 0 = survived, exit 1 = zapped.

    Returns:
        The lightweight runner script source code.
    """
    return '''#!/usr/bin/env python
"""Lightweight test runner for pytest-gremlins — skips full pytest startup."""

import importlib.util
import json
import os
import sys


def setup_import_hooks():
    """Register the gremlin import hooks from sources.json."""
    sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE')
    if not sources_file:
        return

    with open(sources_file) as f:
        instrumented_sources = json.load(f)

    run_code = getattr(__builtins__, 'exec', None) or __builtins__.get('exec')

    from importlib.abc import Loader, MetaPathFinder
    from importlib.machinery import ModuleSpec

    class GremlinLoader(Loader):
        def __init__(self, source, module_name):
            self._source = source
            self._module_name = module_name

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            code = compile(self._source, self._module_name, 'exec')
            run_code(code, module.__dict__)

    class GremlinFinder(MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname in instrumented_sources:
                loader = GremlinLoader(instrumented_sources[fullname], fullname)
                return ModuleSpec(fullname, loader)
            return None

    sys.meta_path.insert(0, GremlinFinder())


def load_test_module(file_path):
    """Import a test module from file path."""
    module_name = file_path.replace('/', '.').replace(os.sep, '.').removesuffix('.py')
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_test(test_spec, rootdir):
    """Run a single test from its node ID. Returns True if passed."""
    parts = test_spec.split('::')
    file_path = parts[0]
    full_path = os.path.join(rootdir, file_path)

    try:
        module = load_test_module(full_path)
        if module is None:
            return False  # Cannot verify = treat as caught

        if len(parts) == 3:
            cls = getattr(module, parts[1], None)
            if cls is None:
                return False  # Cannot verify = treat as caught
            instance = cls()
            method = getattr(instance, parts[2], None)
            if method is None:
                return False  # Cannot verify = treat as caught
            method()
        elif len(parts) == 2:
            func = getattr(module, parts[1], None)
            if func is None:
                return False  # Cannot verify = treat as caught
            func()
        else:
            return False  # Unexpected node ID format = treat as caught

        return True
    except Exception:
        return False


def setup_pythonpath(rootdir):
    """Add project source directories to sys.path.

    Reads pythonpath from pyproject.toml if available, otherwise adds
    common source directories (src/, lib/).
    """
    pyproject = os.path.join(rootdir, 'pyproject.toml')
    added = False
    if os.path.exists(pyproject):
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                tomllib = None

        if tomllib is not None:
            with open(pyproject, 'rb') as f:
                data = tomllib.load(f)
            paths = (data.get('tool', {}).get('pytest', {})
                     .get('ini_options', {}).get('pythonpath', []))
            for p in paths:
                full = os.path.join(rootdir, p)
                if full not in sys.path:
                    sys.path.insert(0, full)
                    added = True

    if not added:
        for candidate in ['src', 'lib', '.']:
            full = os.path.join(rootdir, candidate)
            if os.path.isdir(full) and full not in sys.path:
                sys.path.insert(0, full)

    if rootdir not in sys.path:
        sys.path.insert(0, rootdir)


def main():
    rootdir = os.environ.get('GREMLIN_ROOTDIR', os.getcwd())
    setup_pythonpath(rootdir)
    setup_import_hooks()

    test_specs = sys.argv[1:]
    for spec in test_specs:
        if not run_test(spec, rootdir):
            sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
'''


def _cleanup_instrumented_dir(instrumented_dir: Path | None) -> None:
    """Clean up the temporary instrumented files directory.

    Args:
        instrumented_dir: Path to the directory to remove, or None.
    """
    if instrumented_dir is not None and instrumented_dir.exists():
        shutil.rmtree(instrumented_dir, ignore_errors=True)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """After all tests run, execute mutation testing.

    **Two-phase xdist flow**: when xdist is active, this hook (decorated with
    ``trylast=True``) fires after xdist tears down its workers.  It reconstructs
    the full item list from ``xdist_item_ids`` collected by
    ``pytest_xdist_node_collection_finished``, then runs gremlin generation and
    mutation testing as normal.  Phase 1 (xdist test run) and Phase 2 (gremlins
    mutations) are therefore temporally isolated with no shared mutable state.
    """
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if _is_xdist_worker(session.config):
        return

    config = session.config
    rootdir = _get_rootdir(config)

    if gremlin_session.xdist_active:
        xdist_ids = gremlin_session.xdist_item_ids or []
        if not xdist_ids:
            logger.warning(
                'pytest_sessionfinish: xdist Phase 2 starting with zero item IDs; '
                'pytest_xdist_node_collection_finished may not have fired'
            )
        normalized = _make_node_ids_relative(xdist_ids, rootdir)
        gremlin_session.test_node_ids = {nid: nid for nid in normalized}
        gremlin_session.total_tests = len(normalized)
        logger.debug('pytest_sessionfinish: xdist Phase 2 reconstructed %d test node IDs', len(normalized))
        source_files = _discover_source_files(session, gremlin_session)
        gremlin_session.source_files = source_files
        logger.debug('pytest_sessionfinish: xdist Phase 2 discovered %d source files', len(source_files))
        _generate_gremlins(gremlin_session, source_files, rootdir)
        logger.debug('pytest_sessionfinish: xdist Phase 2 generated %d gremlins', len(gremlin_session.gremlins))

    if not gremlin_session.gremlins:
        return

    _collect_coverage(gremlin_session, rootdir)

    # If pytest-cov is active (--cov was passed), reload its in-memory coverage
    # data from the .coverage file that the pre-scan just wrote. Without this,
    # pytest-cov reports from its outer-session measurement (empty, since the
    # outer session runs no application tests). The pre-scan's .coverage file
    # contains the real per-test coverage data.
    #
    # Detection uses get_plugin('_cov') which is only registered when --cov is
    # actually active. 'pytest_cov' is always present when the package is
    # installed, regardless of whether --cov was passed.
    cov_plugin = config.pluginmanager.get_plugin('_cov')
    if cov_plugin is not None and hasattr(cov_plugin, 'cov') and cov_plugin.cov is not None:
        cov_plugin.cov.load()

    # Choose execution mode based on configuration
    if gremlin_session.batch_enabled:
        results = _run_batch_mutation_testing(session, gremlin_session)
    elif gremlin_session.parallel_enabled:
        results = _run_parallel_mutation_testing(session, gremlin_session)
    else:
        results = _run_mutation_testing(session, gremlin_session)
    gremlin_session.results = results


def _make_node_ids_relative(node_ids: list[str], rootdir: Path) -> list[str]:
    """Convert pytest node IDs to be relative to rootdir.

    Pytest node IDs can be absolute paths in some contexts (e.g., when using
    pytester fixture). This function converts them to relative paths so they
    work correctly when running pytest from within rootdir.

    Also strips any suffixes added by plugins (e.g., pytest-test-categories
    adds "[SMALL]" suffix) since these are display-only decorations.

    Args:
        node_ids: List of pytest node IDs, which may include absolute paths.
        rootdir: The root directory of the project.

    Returns:
        List of node IDs with paths made relative to rootdir.
    """
    relative_node_ids = []
    for node_id in node_ids:
        # Strip any plugin-added suffixes like "[SMALL]", "[MEDIUM]", etc.
        # These are display decorations, not part of the actual node ID
        cleaned_node_id = re.sub(r'\s*\[[A-Z]+\]\s*$', '', node_id)

        # Node IDs have format: path/to/file.py::test_name
        # or just: file.py::test_name
        if '::' in cleaned_node_id:
            path_part, test_part = cleaned_node_id.split('::', 1)
            path_obj = Path(path_part)
            if path_obj.is_absolute() and path_obj.is_relative_to(rootdir):
                relative_path = path_obj.relative_to(rootdir)
                # Use forward slashes for consistency in pytest node IDs
                relative_node_ids.append(f'{relative_path.as_posix()}::{test_part}')
            else:
                relative_node_ids.append(cleaned_node_id)
        # No :: separator, just a path - make it relative if absolute
        else:
            path_obj = Path(cleaned_node_id)
            if path_obj.is_absolute() and path_obj.is_relative_to(rootdir):
                relative_path = path_obj.relative_to(rootdir)
                relative_node_ids.append(relative_path.as_posix())
            else:
                relative_node_ids.append(cleaned_node_id)
    return relative_node_ids


def _collect_coverage(gremlin_session: GremlinSession, rootdir: Path) -> None:
    """Collect coverage data by running tests with coverage.py.

    Runs the test suite with coverage collection using dynamic contexts to
    build a coverage map that maps source lines to the tests that execute them.

    Args:
        gremlin_session: The current gremlin session.
        rootdir: Root directory of the project.
    """
    collector = CoverageCollector()
    gremlin_session.coverage_collector = collector

    test_node_ids = list(gremlin_session.test_node_ids.values())

    # Make node IDs relative to rootdir for subprocess execution
    # Pytest node IDs can be absolute paths in some contexts (e.g., pytester)
    relative_node_ids = _make_node_ids_relative(test_node_ids, rootdir)

    coverage_data = _run_tests_with_coverage(relative_node_ids, rootdir)

    if not coverage_data:
        warnings.warn(
            'Coverage collection returned no data. '
            'If you have --cov in pytest addopts, this may interfere with '
            "gremlins' coverage-guided test selection. "
            'See https://github.com/mikelane/pytest-gremlins/issues/113',
            stacklevel=1,
        )

    gremlin_paths_map: dict[str, str] = {}
    for gremlin in gremlin_session.gremlins:
        abs_path = str(Path(gremlin.file_path).resolve())
        gremlin_paths_map[abs_path] = gremlin.file_path

    for test_name, file_coverage in coverage_data.items():
        normalized_coverage: dict[str, list[int]] = {}
        for file_path, lines in file_coverage.items():
            # Coverage.py stores paths relative to rootdir, so resolve them accordingly
            coverage_path = Path(file_path)
            if coverage_path.is_absolute():
                abs_path = str(coverage_path.resolve())
            else:
                abs_path = str((rootdir / coverage_path).resolve())
            if abs_path in gremlin_paths_map:
                gremlin_path = gremlin_paths_map[abs_path]
                if gremlin_path not in normalized_coverage:
                    normalized_coverage[gremlin_path] = []
                normalized_coverage[gremlin_path].extend(lines)

        if normalized_coverage:
            collector.record_test_coverage(test_name, normalized_coverage)

    gremlin_session.test_selector = TestSelector(collector.coverage_map)
    gremlin_session.prioritized_selector = PrioritizedSelector(collector.coverage_map)


def _run_tests_with_coverage(
    test_node_ids: list[str],
    rootdir: Path,
) -> dict[str, dict[str, list[int]]]:
    """Run all tests with coverage collection using dynamic contexts.

    Uses coverage.py's dynamic_context feature to track which lines are
    covered by which test. This is much faster than running each test
    separately.

    Args:
        test_node_ids: List of pytest node IDs to run.
        rootdir: Root directory of the project.

    Returns:
        Dict mapping test names to their coverage data (file path -> lines).
    """
    coverage_db_path = rootdir / '.coverage'
    coverage_db_path.unlink(missing_ok=True)

    coveragerc_path = rootdir / '.coveragerc.gremlins'
    coveragerc_content = """[run]
source = .
dynamic_context = test_function
"""
    coveragerc_path.write_text(coveragerc_content)

    cmd = [
        sys.executable,
        '-m',
        'coverage',
        'run',
        f'--rcfile={coveragerc_path}',
        '-m',
        'pytest',
        '-o',
        'addopts=',
        *test_node_ids,
        '--tb=no',
        '-q',
    ]

    try:
        subprocess.run(  # Intentional: runs pytest test commands
            cmd,
            cwd=str(rootdir),
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover
        coveragerc_path.unlink(missing_ok=True)
        return {}

    coverage_by_test: dict[str, dict[str, list[int]]] = {}

    try:
        if not coverage_db_path.exists():  # pragma: no cover
            coveragerc_path.unlink(missing_ok=True)
            return {}

        conn = sqlite3.connect(str(coverage_db_path))
        cursor = conn.cursor()

        cursor.execute('SELECT id, context FROM context WHERE context != ""')
        contexts = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute('SELECT id, path FROM file')
        files = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute('SELECT file_id, context_id, numbits FROM line_bits')
        for file_id, context_id, numbits in cursor.fetchall():
            if context_id not in contexts or file_id not in files:
                continue

            context = contexts[context_id]
            test_name = _extract_test_name_from_context(context)

            file_path = files[file_id]

            lines = _decode_numbits(numbits)

            if test_name not in coverage_by_test:
                coverage_by_test[test_name] = {}
            if file_path not in coverage_by_test[test_name]:
                coverage_by_test[test_name][file_path] = []
            coverage_by_test[test_name][file_path].extend(lines)

        conn.close()

    except (sqlite3.Error, OSError) as exc:  # pragma: no cover
        logger.warning('Failed to read coverage data: %s', exc)
    finally:
        try:
            coverage_db_path.unlink(missing_ok=True)
            coveragerc_path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover
            logger.debug('Failed to clean up coverage files: %s', exc)

    return coverage_by_test


def _decode_numbits(numbits: bytes) -> list[int]:
    """Decode coverage.py's numbits format to a list of line numbers.

    The numbits format is a byte array where each bit represents a line number.
    Bit N being set means line N is covered.

    Args:
        numbits: The compressed line number data from coverage.py.

    Returns:
        List of line numbers that were covered.
    """
    return [
        byte_idx * 8 + bit_idx
        for byte_idx, byte_val in enumerate(numbits)
        for bit_idx in range(8)
        if byte_val & (1 << bit_idx)
    ]


def _run_batch_mutation_testing(  # pragma: no cover  # noqa: C901, PLR0912
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing using batch execution for reduced overhead.

    Batch execution reduces subprocess overhead by testing multiple gremlins
    in each subprocess call. Instead of 1 subprocess per gremlin (with ~600ms
    overhead each), we batch gremlins and spawn fewer subprocesses.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        List of results for each gremlin.
    """
    rootdir = _get_rootdir(session.config)
    base_test_command = _build_test_command(gremlin_session.instrumented_dir)
    gremlins = gremlin_session.gremlins

    # Build gremlin -> test mapping for filtering (prioritized order)
    gremlin_tests: dict[str, list[str]] = {}
    for gremlin in gremlins:
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        gremlin_tests[gremlin.gremlin_id] = selected_tests

    # Check cache and separate cached from uncached
    cached_results: list[GremlinResult] = []
    uncached_gremlins: list[Gremlin] = []

    for gremlin in gremlins:
        pardoned_result = _immediate_result_if_pardoned(gremlin)
        if pardoned_result is not None:
            cached_results.append(pardoned_result)
            continue
        selected_tests = gremlin_tests[gremlin.gremlin_id]
        cached_result = _check_cache_for_gremlin(gremlin, selected_tests, gremlin_session)
        if cached_result is not None:
            gremlin_session.cache_hits += 1
            cached_results.append(cached_result)
        else:
            if gremlin_session.cache_enabled:
                gremlin_session.cache_misses += 1
            uncached_gremlins.append(gremlin)

    # Report cache stats
    if cached_results:
        print(f'pytest-gremlins: {len(cached_results)} gremlins from cache, {len(uncached_gremlins)} to test')

    if not uncached_gremlins:
        return cached_results

    # Map gremlin_id -> Gremlin for result reconstruction
    gremlin_by_id = {g.gremlin_id: g for g in uncached_gremlins}

    # Prepare instrumented dir path for env var
    instrumented_dir_str = str(gremlin_session.instrumented_dir) if gremlin_session.instrumented_dir else None

    batch_size = gremlin_session.batch_size
    num_batches = (len(uncached_gremlins) + batch_size - 1) // batch_size
    print(
        f'\npytest-gremlins: Starting batch execution '
        f'({len(uncached_gremlins)} gremlins, {num_batches} batches of {batch_size})'
    )

    gremlins_to_test = [g.gremlin_id for g in uncached_gremlins]

    # For batch execution, we need a unified test command that will work for all gremlins
    # This means running all tests that cover ANY of the gremlins in the batch
    # We preserve prioritization order: tests appearing first in more lists are more specific
    # TODO: optimize by grouping gremlins by their covering tests
    seen_tests: set[str] = set()
    all_covering_tests: list[str] = []
    for gremlin_id in gremlins_to_test:
        for test in gremlin_tests[gremlin_id]:
            if test not in seen_tests:
                seen_tests.add(test)
                all_covering_tests.append(test)

    test_command = _build_filtered_test_command(
        base_test_command,
        all_covering_tests,
        gremlin_session,
    )

    # Execute batches
    executor = BatchExecutor(
        batch_size=batch_size,
        max_workers=gremlin_session.parallel_workers,
        timeout=30,
    )

    worker_results = executor.execute(
        gremlin_ids=gremlins_to_test,
        test_command=test_command,
        rootdir=str(rootdir),
        instrumented_dir=instrumented_dir_str,
        env_vars={},
    )

    # Convert WorkerResults to GremlinResults
    results: list[GremlinResult] = list(cached_results)

    for worker_result in worker_results:
        gremlin_id = worker_result.gremlin_id
        if gremlin_id not in gremlin_by_id:
            continue

        gremlin = gremlin_by_id[gremlin_id]
        selected_tests = gremlin_tests[gremlin_id]
        gremlin_result = GremlinResult(
            gremlin=gremlin,
            status=worker_result.status,
            killing_test=worker_result.killing_test,
            execution_time_ms=worker_result.execution_time_ms,
            error_output=worker_result.error_output,
            selected_tests=selected_tests,
        )
        results.append(gremlin_result)

        # Cache the result
        _cache_gremlin_result(gremlin, selected_tests, gremlin_result, gremlin_session)

    return results


def _run_parallel_mutation_testing(  # pragma: no cover  # noqa: C901, PLR0912, PLR0915
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing in parallel across multiple workers.

    Uses a worker pool to execute gremlin tests concurrently for faster
    results on multi-core machines.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        List of results for each gremlin.
    """
    rootdir = _get_rootdir(session.config)
    base_test_command = _build_test_command(gremlin_session.instrumented_dir)
    gremlins = gremlin_session.gremlins

    # Build gremlin -> test mapping for filtering (prioritized order)
    gremlin_tests: dict[str, list[str]] = {}
    for gremlin in gremlins:
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        gremlin_tests[gremlin.gremlin_id] = selected_tests

    # Check cache and separate cached from uncached
    cached_results: list[GremlinResult] = []
    uncached_gremlins: list[Gremlin] = []

    for gremlin in gremlins:
        pardoned_result = _immediate_result_if_pardoned(gremlin)
        if pardoned_result is not None:
            cached_results.append(pardoned_result)
            continue
        selected_tests = gremlin_tests[gremlin.gremlin_id]
        cached_result = _check_cache_for_gremlin(gremlin, selected_tests, gremlin_session)
        if cached_result is not None:
            gremlin_session.cache_hits += 1
            cached_results.append(cached_result)
        else:
            if gremlin_session.cache_enabled:
                gremlin_session.cache_misses += 1
            uncached_gremlins.append(gremlin)

    # Report cache stats
    if cached_results:
        print(f'pytest-gremlins: {len(cached_results)} gremlins from cache, {len(uncached_gremlins)} to test')

    if not uncached_gremlins:
        return cached_results

    # Run uncached gremlins in parallel
    aggregator = ResultAggregator(total_gremlins=len(uncached_gremlins))

    # Prepare instrumented dir path for env var
    instrumented_dir_str = str(gremlin_session.instrumented_dir) if gremlin_session.instrumented_dir else None

    # Map gremlin_id -> Gremlin for result reconstruction
    gremlin_by_id = {g.gremlin_id: g for g in uncached_gremlins}

    print(f'\npytest-gremlins: Starting parallel execution with {gremlin_session.parallel_workers or "auto"} workers')

    with WorkerPool(
        max_workers=gremlin_session.parallel_workers,
        timeout=30,
    ) as pool:
        # Submit all gremlins
        futures = {}
        for gremlin in uncached_gremlins:
            selected_tests = gremlin_tests[gremlin.gremlin_id]

            test_command = _build_filtered_test_command(
                base_test_command,
                selected_tests,
                gremlin_session,
            )

            future = pool.submit(
                gremlin_id=gremlin.gremlin_id,
                test_command=test_command,
                rootdir=str(rootdir),
                instrumented_dir=instrumented_dir_str,
                env_vars={},
            )
            futures[future] = gremlin.gremlin_id

        # Collect results as they complete
        for future in as_completed(futures):
            gremlin_id = futures[future]
            try:
                worker_result = future.result()
                aggregator.add_result(worker_result)
            except Exception as execution_error:
                aggregator.add_error(gremlin_id, execution_error)

            # Progress reporting
            completed, total = aggregator.get_progress()
            print(f'\rpytest-gremlins: Progress {completed}/{total}', end='', flush=True)

    print()  # New line after progress

    # Convert WorkerResults to GremlinResults and cache them
    results: list[GremlinResult] = list(cached_results)
    for worker_result in aggregator.get_results():
        gremlin_id = worker_result.gremlin_id
        if gremlin_id not in gremlin_by_id:
            continue

        gremlin = gremlin_by_id[gremlin_id]
        selected_tests = gremlin_tests[gremlin_id]
        gremlin_result = GremlinResult(
            gremlin=gremlin,
            status=worker_result.status,
            killing_test=worker_result.killing_test,
            execution_time_ms=worker_result.execution_time_ms,
            error_output=worker_result.error_output,
            selected_tests=selected_tests,
        )
        results.append(gremlin_result)

        # Cache the result
        _cache_gremlin_result(gremlin, selected_tests, gremlin_result, gremlin_session)

    return results


def _run_mutation_testing_inprocess(
    executor_choice: str,
    gremlin_session: GremlinSession,
    rootdir: Path,
    base_test_command: list[str],
) -> list[GremlinResult]:
    """Run mutation testing using fork or in-process executor."""
    gremlin_module_map = _build_gremlin_module_map(gremlin_session.gremlins, rootdir)
    test_specs = [arg for arg in base_test_command if '::' in arg]
    timeout = gremlin_session.timeout if hasattr(gremlin_session, 'timeout') else 30
    batch_size = gremlin_session.batch_size if hasattr(gremlin_session, 'batch_size') else 50

    gremlin_ids = [g.gremlin_id for g in gremlin_session.gremlins if not g.pardoned]

    if executor_choice == 'fork':
        executor: InProcessExecutor | ForkExecutor = ForkExecutor(batch_size=batch_size, timeout=timeout)
    else:
        executor = InProcessExecutor(timeout=timeout)

    worker_results = executor.execute(gremlin_ids, gremlin_module_map, test_specs)

    results: list[GremlinResult] = []
    gremlin_by_id = {g.gremlin_id: g for g in gremlin_session.gremlins}
    for worker_result in worker_results:
        gremlin = gremlin_by_id.get(worker_result.gremlin_id)
        if gremlin is None:
            continue
        results.append(
            GremlinResult(
                gremlin=gremlin,
                status=worker_result.status,
                killing_test=worker_result.killing_test,
                execution_time_ms=worker_result.execution_time_ms,
                error_output=worker_result.error_output,
            )
        )

    # Add pardoned gremlins
    for gremlin in gremlin_session.gremlins:
        pardoned_result = _immediate_result_if_pardoned(gremlin)
        if pardoned_result is not None:
            results.append(pardoned_result)

    return results


def _run_mutation_testing(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing for all gremlins.

    Uses incremental caching when enabled to skip unchanged gremlins.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        List of results for each gremlin.
    """
    results: list[GremlinResult] = []
    rootdir = _get_rootdir(session.config)
    base_test_command = _build_test_command(gremlin_session.instrumented_dir)

    executor_choice = (
        session.config.option.gremlin_executor if hasattr(session.config.option, 'gremlin_executor') else 'subprocess'
    )

    if executor_choice in ('fork', 'inprocess'):
        return _run_mutation_testing_inprocess(
            executor_choice,
            gremlin_session,
            rootdir,
            base_test_command,
        )

    for i, gremlin in enumerate(gremlin_session.gremlins, 1):
        pardoned_result = _immediate_result_if_pardoned(gremlin)
        if pardoned_result is not None:
            results.append(pardoned_result)
            continue
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        test_count = len(selected_tests)
        total = gremlin_session.total_tests

        # Check cache for existing result
        cached_result = _check_cache_for_gremlin(gremlin, selected_tests, gremlin_session)
        if cached_result is not None:
            gremlin_session.cache_hits += 1
            _report_gremlin_cache_hit(i, len(gremlin_session.gremlins), gremlin)
            results.append(cached_result)
            continue

        if gremlin_session.cache_enabled:
            gremlin_session.cache_misses += 1
            _report_gremlin_cache_miss(i, len(gremlin_session.gremlins), gremlin)

        _report_gremlin_progress(i, len(gremlin_session.gremlins), gremlin, test_count, total)

        test_command = _build_filtered_test_command(
            base_test_command,
            selected_tests,
            gremlin_session,
        )
        gremlin_result = _test_gremlin(
            gremlin,
            test_command,
            rootdir,
            gremlin_session.instrumented_dir,
        )
        # Attach selected tests for debuggability in reports
        gremlin_result = GremlinResult(
            gremlin=gremlin_result.gremlin,
            status=gremlin_result.status,
            killing_test=gremlin_result.killing_test,
            execution_time_ms=gremlin_result.execution_time_ms,
            error_output=gremlin_result.error_output,
            selected_tests=selected_tests,
        )

        # Cache the result for next run
        _cache_gremlin_result(gremlin, selected_tests, gremlin_result, gremlin_session)

        results.append(gremlin_result)

    return results


def _build_test_hashes_for_gremlin(
    selected_tests: Sequence[str],
    gremlin_session: GremlinSession,
) -> dict[str, str]:
    """Build test hashes for the tests that cover a gremlin.

    Maps test names to their file content hashes. Test names can be in different
    formats (simple function, module.function, TestClass.method), so this function
    tries variations to find the corresponding node ID and file hash.

    Args:
        selected_tests: Sequence of test names that cover the gremlin.
        gremlin_session: The current gremlin session with test metadata.

    Returns:
        Dictionary mapping test names to their file content hashes.
    """
    test_hashes: dict[str, str] = {}
    for test_name in selected_tests:
        node_id = gremlin_session.test_node_ids.get(test_name, '')
        if not node_id:
            simple_name = test_name.split('.')[-1]
            node_id = gremlin_session.test_node_ids.get(simple_name, '')

        if '::' in node_id:
            test_file = node_id.split('::')[0]
            for file_path, file_hash in gremlin_session.test_hashes.items():
                if file_path.endswith(test_file) or test_file in file_path:
                    test_hashes[test_name] = file_hash
                    break

    return test_hashes


def _check_cache_for_gremlin(
    gremlin: Gremlin,
    selected_tests: Sequence[str],
    gremlin_session: GremlinSession,
) -> GremlinResult | None:
    """Check cache for existing result for this gremlin.

    Args:
        gremlin: The gremlin to check cache for.
        selected_tests: Sequence of tests that cover this gremlin.
        gremlin_session: The current gremlin session.

    Returns:
        Cached GremlinResult if found and valid, None otherwise.
    """
    if not gremlin_session.cache_enabled or gremlin_session.cache is None:
        return None

    source_hash = gremlin_session.source_hashes.get(gremlin.file_path, '')
    if not source_hash:
        return None

    test_hashes = _build_test_hashes_for_gremlin(selected_tests, gremlin_session)

    cached = gremlin_session.cache.get_cached_result(
        gremlin_id=gremlin.gremlin_id,
        source_hash=source_hash,
        test_hashes=test_hashes,
    )

    if cached is None:
        return None

    status = GremlinResultStatus(cached['status'])
    return GremlinResult(
        gremlin=gremlin,
        status=status,
        killing_test=cached.get('killing_test'),
        execution_time_ms=cached.get('execution_time_ms'),
        error_output=cached.get('error_output', ''),
    )


def _cache_gremlin_result(
    gremlin: Gremlin,
    selected_tests: Sequence[str],
    result: GremlinResult,
    gremlin_session: GremlinSession,
) -> None:
    """Cache the result for a gremlin.

    Args:
        gremlin: The gremlin that was tested.
        selected_tests: Sequence of tests that covered this gremlin.
        result: The result to cache.
        gremlin_session: The current gremlin session.
    """
    if not gremlin_session.cache_enabled or gremlin_session.cache is None:
        return

    source_hash = gremlin_session.source_hashes.get(gremlin.file_path, '')
    if not source_hash:
        return

    test_hashes = _build_test_hashes_for_gremlin(selected_tests, gremlin_session)

    # Use deferred writes to batch commits for better performance
    gremlin_session.cache.cache_result_deferred(
        gremlin_id=gremlin.gremlin_id,
        source_hash=source_hash,
        test_hashes=test_hashes,
        result=CachedGremlinResult(
            status=result.status.value,
            killing_test=result.killing_test,
            execution_time_ms=result.execution_time_ms,
            error_output=result.error_output,
        ),
    )


def _report_gremlin_cache_hit(
    index: int,
    total_gremlins: int,
    gremlin: Gremlin,
) -> None:
    """Report a cache hit for a gremlin.

    Args:
        index: Current gremlin index (1-based).
        total_gremlins: Total number of gremlins.
        gremlin: The gremlin that had a cache hit.
    """
    prefix = f'Gremlin {index}/{total_gremlins}: {gremlin.gremlin_id}'
    print(f'{prefix} - cache hit (skipping)')


def _report_gremlin_cache_miss(
    index: int,
    total_gremlins: int,
    gremlin: Gremlin,
) -> None:
    """Report a cache miss for a gremlin.

    Args:
        index: Current gremlin index (1-based).
        total_gremlins: Total number of gremlins.
        gremlin: The gremlin that had a cache miss.
    """
    prefix = f'Gremlin {index}/{total_gremlins}: {gremlin.gremlin_id}'
    print(f'{prefix} - cache miss')


def _select_tests_for_gremlin_prioritized(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> list[str]:
    """Select tests for a gremlin, ordered by specificity (most specific first).

    Uses the PrioritizedSelector to return tests in an order that maximizes
    the chance of catching the mutation quickly. Tests covering fewer lines
    are considered more specific and run first.

    When coverage-guided selection finds no covering tests, falls back to
    running all tests. This handles module-level code (class attribute defaults,
    module constants) that executes at import time before any test function
    runs. Coverage.py records these lines under the empty context, which isn't
    associated with any specific test.

    Args:
        gremlin: The gremlin to select tests for.
        gremlin_session: The current gremlin session.

    Returns:
        List of test names ordered by specificity (most specific first).
    """
    if gremlin_session.prioritized_selector is None:
        return list(gremlin_session.test_node_ids.keys())

    selected = gremlin_session.prioritized_selector.select_tests_prioritized(gremlin)
    if not selected:
        return list(gremlin_session.test_node_ids.keys())

    return selected


def _report_gremlin_progress(
    index: int,
    total_gremlins: int,
    gremlin: Gremlin,
    test_count: int,
    total_tests: int,
) -> None:
    """Report progress for a gremlin being tested.

    Args:
        index: Current gremlin index (1-based).
        total_gremlins: Total number of gremlins.
        gremlin: The gremlin being tested.
        test_count: Number of tests selected for this gremlin.
        total_tests: Total number of tests in the suite.
    """
    prefix = f'Gremlin {index}/{total_gremlins}: {gremlin.gremlin_id}'
    print(f'{prefix} - running {test_count}/{total_tests} tests')


def _build_filtered_test_command(
    base_command: list[str],
    selected_tests: Sequence[str],
    gremlin_session: GremlinSession,
) -> list[str]:
    """Build a test command that runs only the selected tests.

    The order of selected_tests is preserved in the resulting command,
    enabling prioritized test execution (most specific tests first).

    Args:
        base_command: The base test command.
        selected_tests: Sequence of test names to run (order is preserved).
        gremlin_session: The current gremlin session.

    Returns:
        Command list with test node IDs appended in the same order.
    """
    command = list(base_command)

    node_ids = [
        gremlin_session.test_node_ids[test_name]
        for test_name in selected_tests
        if test_name in gremlin_session.test_node_ids
    ]

    if node_ids:
        command.extend(node_ids)

    return command


def _pytest_cov_available() -> bool:
    """Check if pytest-cov is available in the current environment.

    The check runs in the parent process (where gremlins is running),
    not the subprocess.  This is correct because gremlins and the target
    project share the same venv.

    Returns:
        True when ``pytest-cov`` is importable, False otherwise.
    """
    try:
        import pytest_cov  # type: ignore  # noqa: F401, PLC0415
    except ImportError:
        return False
    else:
        return True


def _build_test_command(instrumented_dir: Path | None) -> list[str]:
    """Build the command to run tests.

    If an instrumented directory is provided, uses the bootstrap script
    to register import hooks before running pytest. Otherwise, runs
    pytest directly.

    ``--no-cov`` is only appended when ``pytest-cov`` is installed so
    that projects without the plugin do not receive an unknown CLI flag
    (which causes pytest exit-code 4).

    Args:
        instrumented_dir: Directory containing bootstrap infrastructure, or None.

    Returns:
        Command list to run tests.
    """
    if instrumented_dir is not None:
        bootstrap_script = instrumented_dir / 'gremlin_bootstrap.py'
        command = [
            sys.executable,
            str(bootstrap_script),
            '-x',
            '--tb=no',
            '-q',
            '-o',
            'addopts=',
        ]
    else:
        command = [
            sys.executable,
            '-m',
            'pytest',
            '-x',
            '--tb=no',
            '-q',
            '-o',
            'addopts=',
        ]

    if _pytest_cov_available():
        command.append('--no-cov')

    return command


def _immediate_result_if_pardoned(gremlin: Gremlin) -> GremlinResult | None:
    """Return a PARDONED result immediately if the gremlin is pardoned, else None.

    Called at the top of every execution loop. Pardoned gremlins must never
    have subprocess tests run against them — they exit the loop here.

    Args:
        gremlin: The gremlin to check.

    Returns:
        A GremlinResult with PARDONED status if pardoned, otherwise None.
    """
    if gremlin.pardoned:
        return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.PARDONED)
    return None


def _test_gremlin(
    gremlin: Gremlin,
    test_command: list[str],
    rootdir: Path,
    instrumented_dir: Path | None,
) -> GremlinResult:
    """Test a single gremlin by running tests with the mutation active.

    The subprocess runs via a bootstrap script that registers import hooks
    to intercept module imports and provide instrumented code. The active
    gremlin ID is passed via the ACTIVE_GREMLIN environment variable.

    Args:
        gremlin: The gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory of the project.
        instrumented_dir: Directory containing bootstrap infrastructure.

    Returns:
        Result of testing the gremlin.
    """
    env = os.environ.copy()
    env[ACTIVE_GREMLIN_ENV_VAR] = gremlin.gremlin_id
    env['GREMLIN_ROOTDIR'] = str(rootdir)

    if instrumented_dir is not None:
        sources_file = instrumented_dir / 'sources.json'
        env[GREMLIN_SOURCES_ENV_VAR] = str(sources_file)

    # Use lightweight runner if available (skips full pytest startup)
    lightweight_cmd = build_lightweight_command(test_command, env)
    effective_command = lightweight_cmd if lightweight_cmd is not None else test_command

    try:
        subprocess_outcome = subprocess.run(  # Intentional: runs pytest test commands
            effective_command,
            cwd=str(rootdir),
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )

        # pytest uses specific exit codes. Only exit code 1 means tests ran
        # and failed (i.e. the mutation was caught). Other non-zero exit codes
        # indicate errors (collection/import/internal) and should not be counted
        # as zapped.
        if subprocess_outcome.returncode == 0:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.SURVIVED,
            )
        if subprocess_outcome.returncode == 1:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ZAPPED,
                killing_test='unknown',
            )
        error_output = ''
        if subprocess_outcome.stderr:
            error_output = subprocess_outcome.stderr.decode(errors='replace')[:2000]
        logger.debug(
            'Gremlin %s error (exit %d): %s',
            gremlin.gremlin_id,
            subprocess_outcome.returncode,
            error_output[:200],
        )
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
            error_output=error_output,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.TIMEOUT,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning('Error testing gremlin %s: %s', gremlin.gremlin_id, exc)
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
            error_output=str(exc)[:2000],
        )


def _write_html_report(score: MutationScore, rootdir: Path, html_dir: Path | None = None) -> Path:
    """Write HTML report to file.

    Args:
        score: The MutationScore to write.
        rootdir: Root directory of the project.
        html_dir: Custom output directory, or ``None`` for the default
            ``<rootdir>/coverage/gremlins/`` location.

    Returns:
        Path to the written HTML report.
    """
    reporter = HtmlReporter()
    output_path = resolve_html_output_path(rootdir=rootdir, html_dir=html_dir)
    reporter.write_report(score, output_path)
    return output_path


def _write_json_report(score: MutationScore, rootdir: Path) -> Path:
    """Write JSON report to file.

    Args:
        score: The MutationScore to write.
        rootdir: Root directory of the project.

    Returns:
        Path to the written JSON report.
    """
    reporter = JsonReporter()
    # TODO(#308): add --gremlins-json-path flag for parity with --gremlins-html-dir
    output_path = rootdir / 'coverage' / 'gremlins' / 'gremlins.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    reporter.write_report(score, output_path)
    return output_path


def pytest_terminal_summary(  # noqa: C901, PLR0912, PLR0915
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,  # noqa: ARG001
    config: pytest.Config,
) -> None:
    """Add mutation testing results to terminal output."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if not gremlin_session.gremlins:
        terminalreporter.write_sep('=', 'pytest-gremlins mutation report')
        terminalreporter.write_line('')
        if gremlin_session.target_paths:
            terminalreporter.write_line('No gremlins found in source code. Searched paths:')
            for searched_path in gremlin_session.target_paths:
                terminalreporter.write_line(f'  - {searched_path}')
        else:
            terminalreporter.write_line('No gremlins found: no source paths were discovered.')
            terminalreporter.write_line('')
            terminalreporter.write_line('pytest-gremlins looks for source code in this order:')
            terminalreporter.write_line('  1. --gremlin-targets CLI option')
            terminalreporter.write_line('  2. [tool.pytest-gremlins] paths in pyproject.toml')
            terminalreporter.write_line('  3. [tool.setuptools] package config in pyproject.toml')
            terminalreporter.write_line('  4. [project].name heuristic in pyproject.toml')
            terminalreporter.write_line('  5. setup.cfg [options] / [options.packages.find]')
            terminalreporter.write_line('  6. Installed package metadata (importlib.metadata)')
            terminalreporter.write_line('  7. src/ directory')
            terminalreporter.write_line('')
            terminalreporter.write_line(
                'If your source code is elsewhere, use: pytest --gremlins --gremlin-targets=your_package'
            )
        terminalreporter.write_line('')
        terminalreporter.write_sep('=', '')
        return

    score = MutationScore.from_results(gremlin_session.results)

    # Write file-based reports as requested
    rootdir = _get_rootdir(config)

    if 'html' in gremlin_session.report_formats:
        raw_html_dir = config.getoption('gremlins_html_dir', default=None)
        html_dir = Path(raw_html_dir) if raw_html_dir is not None else None
        try:
            report_path = _write_html_report(score, rootdir=rootdir, html_dir=html_dir)
            terminalreporter.write_line(f'HTML report written to: {report_path}')
        except OSError as exc:
            logger.warning('Failed to write HTML report: %s', exc)
            terminalreporter.write_line(f'HTML report write failed: {exc}')

    if 'json' in gremlin_session.report_formats:
        try:
            json_path = _write_json_report(score, rootdir=rootdir)
            terminalreporter.write_line(f'JSON report written to: {json_path}')
        except OSError as exc:
            logger.warning('Failed to write JSON report: %s', exc)
            terminalreporter.write_line(f'JSON report write failed: {exc}')

    terminalreporter.write_sep('=', 'pytest-gremlins mutation report')
    terminalreporter.write_line('')

    if score.total == 0:
        terminalreporter.write_line('No gremlins tested.')
    else:
        zapped_pct = round(score.zapped / score.total * 100)
        survived_pct = round(score.survived / score.total * 100)
        timeout_pct = round(score.timeout / score.total * 100)
        error_pct = round(score.error / score.total * 100)

        terminalreporter.write_line(f'Zapped: {score.zapped} gremlins ({zapped_pct}%)')
        terminalreporter.write_line(f'Survived: {score.survived} gremlins ({survived_pct}%)')
        if score.timeout > 0:
            terminalreporter.write_line(f'Timeout: {score.timeout} gremlins ({timeout_pct}%)')
        if score.error > 0:
            terminalreporter.write_line(f'Error: {score.error} gremlins ({error_pct}%)')
        if score.pardoned > 0:
            terminalreporter.write_line(f'Pardoned: {score.pardoned} gremlins (excluded from score)')

        # Show cache statistics if caching was enabled
        if gremlin_session.cache_enabled:
            total_cache = gremlin_session.cache_hits + gremlin_session.cache_misses
            if total_cache > 0:
                hit_rate = round(gremlin_session.cache_hits / total_cache * 100)
                terminalreporter.write_line('')
                terminalreporter.write_line(
                    f'Cache: {gremlin_session.cache_hits} hits, '
                    f'{gremlin_session.cache_misses} misses ({hit_rate}% hit rate)'
                )

        survivors = score.top_survivors(limit=10)
        if survivors:
            terminalreporter.write_line('')
            terminalreporter.write_line('Top surviving gremlins:')
            for result in survivors:
                gremlin = result.gremlin
                location = f'{gremlin.file_path}:{gremlin.line_number}'
                terminalreporter.write_line(f'  {location:<30} {gremlin.description:<20} ({gremlin.operator_name})')

    terminalreporter.write_line('')
    if 'html' not in gremlin_session.report_formats:
        terminalreporter.write_line('Run with --gremlin-report=html for detailed report.')
    terminalreporter.write_sep('=', '')

    if gremlin_session.audit_pardons and score.pardoned > 0:
        terminalreporter.write_line('')
        terminalreporter.write_line('Pardoned gremlins audit:')
        for gremlin_result in score.results:
            if gremlin_result.status == GremlinResultStatus.PARDONED:
                pardoned_gremlin = gremlin_result.gremlin
                reason = pardoned_gremlin.pardon_reason or '(no reason)'
                location = f'{pardoned_gremlin.file_path}:{pardoned_gremlin.line_number}'
                terminalreporter.write_line(f'  {location}  {reason}')

    if gremlin_session.strict_pardons and score.pardoned > 0:
        pytest.exit(f'--strict-pardons: {score.pardoned} pardoned gremlins exist', returncode=1)

    max_pardons_pct = gremlin_session.max_pardons_pct
    if max_pardons_pct is not None and score.total > 0:
        pardoned_pct = score.pardoned / score.total * 100
        if pardoned_pct > max_pardons_pct:
            logger.warning(
                'max-pardons-pct exceeded: %.1f%% pardoned (%d of %d) — limit is %.1f%%',
                pardoned_pct,
                score.pardoned,
                score.total,
                max_pardons_pct,
            )
            terminalreporter.write_line(
                f'Max pardons exceeded: {pardoned_pct:.1f}% pardoned ({score.pardoned} of {score.total})'
                f' — limit is {max_pardons_pct:.1f}%'
            )
            pytest.exit(
                f'Pardoned gremlins ({pardoned_pct:.1f}%) exceed the {max_pardons_pct:.1f}% limit.'
                f' Zap the {score.pardoned} pardoned gremlins or raise --gremlin-max-pardons-pct.',
                returncode=1,
            )
        else:
            logger.info(
                'max-pardons-pct OK: %.1f%% pardoned (%d of %d) — limit is %.1f%%',
                pardoned_pct,
                score.pardoned,
                score.total,
                max_pardons_pct,
            )

    max_pardons = gremlin_session.max_pardons
    if max_pardons is not None:
        if score.pardoned > max_pardons:
            logger.warning(
                'max-pardons exceeded: %d pardoned — limit is %d',
                score.pardoned,
                max_pardons,
            )
            terminalreporter.write_line(
                f'Max pardons exceeded: {score.pardoned} pardoned gremlins — limit is {max_pardons}'
            )
            pytest.exit(
                f'--max-pardons={max_pardons} exceeded — {score.pardoned} pardons active (limit: {max_pardons}).'
                f' Zap the {score.pardoned} pardoned gremlins or raise --max-pardons.',
                returncode=1,
            )
        else:
            logger.info(
                'max-pardons OK: %d pardoned — limit is %d',
                score.pardoned,
                max_pardons,
            )


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    """Clean up after pytest-gremlins."""
    gremlin_session = _get_session()
    if gremlin_session is not None:
        _cleanup_instrumented_dir(gremlin_session.instrumented_dir)
        # Close the cache to release database connection
        if gremlin_session.cache is not None:
            gremlin_session.cache.close()
    _set_session(None)
