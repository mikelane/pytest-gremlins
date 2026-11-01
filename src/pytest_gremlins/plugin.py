"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

import argparse
import ast
import base64
import collections.abc
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import (
    dataclass,
    field,
)
from dataclasses import replace as dataclass_replace
import difflib
from enum import Enum
import fnmatch
import functools
import importlib.util
import inspect
from itertools import pairwise
import json
import logging
import os
from pathlib import Path
import pickle  # nosec B403 - only pickles the instrumented tree for its own subprocess; nothing is unpickled here
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tokenize
from typing import (
    TYPE_CHECKING,
)
import zlib

from coverage.exceptions import CoverageException
import pytest

from pytest_gremlins import node_id_args
from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import (
    MILLISECONDS_PER_SECOND,
    NO_RERUNS,
    IncrementalCache,
    RerunBudget,
    subprocess_optimize_level,
)
from pytest_gremlins.cache.types import CachedGremlinResult
from pytest_gremlins.config import (
    MAX_TIMEOUT_SECONDS,
    VALID_REPORT_FORMATS,
    GremlinConfig,
    discover_by_importlib_metadata,
    discover_by_project_name,
    discover_by_setup_cfg,
    discover_source_paths,
    load_config,
    merge_configs,
)
from pytest_gremlins.control_run import (
    MAX_SELECTION_FAILURE_OUTPUT_CHARS,
    SELECTION_FAILS_TO_LOAD_PREFIX,
    TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX,
    UNATTRIBUTABLE_MARKER,
    ControlRunOutcome,
    UnmutatedRunOutcome,
    build_diagnostic,
    run_control,
    run_unmutated,
)
from pytest_gremlins.coverage import (
    CoverageCollector,
    PrioritizedSelector,
    TestSelector,
)
from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin
from pytest_gremlins.coverage.nodeid_markers import strip_marker_suffix
from pytest_gremlins.gremlins_options import addopts_without_gremlins
from pytest_gremlins.instrumentation import origin_finder
from pytest_gremlins.instrumentation.origin_finder import (
    file_identity,
    normalize_origin,
)
from pytest_gremlins.instrumentation.spawn_hook import (
    SOURCES_FILE_ENV_VAR,
    export_spawn_hook,
    write_spawn_hook,
)
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.instrumentation.transformer import (
    get_default_registry,
    transform_source,
)
from pytest_gremlins.node_id_file import command_with_node_ids_file
from pytest_gremlins.operators.entry_points import (
    GremlinEntryPointWarning,
    discard_warning,
    load_entry_point_operators,
)
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.batch_executor import BatchExecutor
from pytest_gremlins.parallel.exit_codes import (
    COLLECTION_KILLING_TEST,
    GREMLIN_COLLECTION_FAILED_EXIT_CODE,
)
from pytest_gremlins.parallel.lightweight import (
    LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE,
    REWRITE_API_BROKEN_PREFIX,
    build_lightweight_command,
    describe_runner_error,
)
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.reporting.html import (
    HtmlReporter,
    resolve_html_output_path,
)
from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import (
    CAPPED_LIMIT_ADVICE,
    TIMEOUT_NOT_CONFIRMED_PREFIX,
    GremlinResult,
    GremlinResultStatus,
    limit_is_capped,
    scaled_limit_note,
)
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.rerun_options import (
    RerunIniResolution,
    baseline_rerun_warning,
    expand_argument_files,
    mutant_timeout_for_items,
    rerun_cache_settings,
    rerun_ini_as_gremlin_runs_read,
    rerun_keys_set_in,
    rerun_options_in,
    resolve_rerun_ini,
    scaled_mutant_timeout,
    session_rerun_backoff_factor,
    session_rerun_budget,
    unforwarded_rerun_key_warning,
)
from pytest_gremlins.xdist_options import (
    addopts_without_xdist,
    env_with_stripped_addopts,
    env_without_xdist_addopts,
)

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Sequence,
    )

    import coverage

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.operators import GremlinOperator


DEFAULT_TEST_FILE_PATTERNS = ('test_*.py', '*_test.py')
_XDIST_AVAILABLE = importlib.util.find_spec('xdist') is not None


logger = logging.getLogger(__name__)

GREMLIN_SOURCES_ENV_VAR = SOURCES_FILE_ENV_VAR


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


DEFAULT_COVERAGE_TIMEOUT_SECONDS = 120
DEFAULT_MUTANT_TIMEOUT_SECONDS = 30
DEFAULT_BATCH_SIZE = 10
DEFAULT_REPORT_FORMATS: tuple[str, ...] = ('console',)
MAX_SELECTION_IDS_IN_MESSAGE = 5
"""Node ids named in a downgraded-timeout message before the rest are summarised as ``(and N more)``."""
UNMAPPED_SELECTION_PREFIX = 'no verdict: the gremlin has no test to run'
"""Start of the error for a gremlin whose whole selection has no pytest node id (issue #571)."""
TIMEOUT_CONFIRMATION_HEADROOM = 0.5
"""Share of ``mutant_timeout`` the unmutated confirmation run may use for a timeout to stay a kill.

One yes/no sample against the limit has no margin: an unmutated run that finishes at 99% of the limit
would keep a survivor as a kill on a lucky run. Requiring the unmutated run to fit in half the limit
means a real hang clears a 2x margin, while ordinary run-to-run noise does not.
"""


class CoveragePrescanTimeoutError(Exception):
    """Raised when the coverage pre-scan subprocess exceeds its time limit (issue #503)."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f'coverage pre-scan exceeded {seconds}s')
        self.seconds = seconds


class CoveragePrescanLaunchError(Exception):
    """Raised when the operating system cannot start the coverage pre-scan subprocess (issue #485)."""

    def __init__(self, cause: OSError) -> None:
        super().__init__(f'coverage pre-scan could not start ({cause})')
        self.cause = cause


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
        test_hashes: Content hashes for test files, keyed by the file part of their normalized node ids.
        cache_hits: Number of cache hits in this session.
        cache_misses: Number of cache misses in this session.
        parallel_enabled: Whether parallel execution is enabled.
        parallel_workers: Number of parallel workers (None = CPU count).
        batch_enabled: Whether batch execution mode is enabled.
        batch_size: Number of gremlins per batch in batch mode.
        load_failures_attributable: ``False`` once the unmutated control run failed to load the suite
            in the gremlin subprocess; load failures then say nothing about a mutant (issue #550).
        unmutated_load_checks: Memo of unmutated ``--collect-only`` results keyed by the ordered node ids
            (pytest collects them in command order, and loading can depend on it), so a selection
            shared by many gremlins is checked once.
        unmutated_timeout_checks: Memo of unmutated timed runs keyed by the ordered node ids, so a
            selection shared by many timed-out gremlins is run once (issue #565).
        xdist_item_ids: Test node IDs captured from the first xdist worker after
            collection finishes.  ``None`` until the hook fires; ``[]`` if the
            worker collected nothing.
        coverage_mode: Whether to reuse pytest-cov's coverage (PIGGYBACK) or
            rely on the coverage pre-scan subprocess (PRIVATE).
        exclude_patterns: Glob patterns from ``[tool.pytest-gremlins] exclude``
            used to skip matching files during source discovery.
        test_name_to_node_ids: Reverse index mapping bare function names to
            their full pytest node IDs.  Built at session setup for O(1)
            lookup when resolving coverage contexts.
        coverage_timeout: Seconds the coverage pre-scan may run before it is
            abandoned and coverage-guided test selection is disabled (issue #503).
            Like ``mutant_timeout``, it is the configured limit scaled by the session's
            pytest-rerunfailures budget (issue #673).
        coverage_attempt_timeout: The configured pre-scan limit before scaling, or ``None``
            when the session does not know it (a hand-built session).
        mutant_timeout: Seconds one gremlin's test run may take before the gremlin
            is reported as a timeout.  This is the configured limit already scaled by the
            session's pytest-rerunfailures budget (issue #655), so the timeout warning and the
            cache key see the effective value.
        mutant_attempt_timeout: The configured per-gremlin limit before scaling, or ``None``
            when the session does not know it (a hand-built session).
        terminal_notices: Lines for the terminal summary, written directly rather than through
            ``logging`` (which pytest captures) or ``warnings.warn`` (which ``filterwarnings = error``
            turns into a crash).  Add one with :func:`_queue_terminal_notice`.
        skipped_files: Target files dropped because instrumentation raised, mapped to the
            ``ExceptionType: message`` that dropped them (issue #638).
        preserved_addopts: The project's pytest ``addopts`` with pytest-cov flags
            stripped (see :func:`_addopts_without_cov`), threaded into the subprocess
            runs as ``-o addopts=<...>`` so collection-affecting options such as
            ``--import-mode=importlib`` survive (issue #424).  ``''`` clears all addopts.
            xdist options are left intact here; the coverage pre-scan and every per-gremlin
            run strip them (see :func:`pytest_gremlins.xdist_options.addopts_without_xdist`).
        doctest_ini_overrides: The session's resolved doctest ini values as ``-o key=value`` argument pairs,
            passed as top-level arguments because pytest before 9.1 ignores a ``-o`` nested in ``addopts`` (#719).
    """

    enabled: bool = False
    operators: list[GremlinOperator] = field(default_factory=list)
    report_formats: list[str] = field(default_factory=lambda: list(DEFAULT_REPORT_FORMATS))
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
    batch_size: int = DEFAULT_BATCH_SIZE
    xdist_item_ids: list[str] | None = None
    load_failures_attributable: bool = True
    unmutated_load_checks: dict[tuple[str, ...], ControlRunOutcome] = field(default_factory=dict)
    unmutated_timeout_checks: dict[tuple[str, ...], UnmutatedRunOutcome] = field(default_factory=dict)
    xdist_active: bool = False
    xdist_loaded: bool = False
    xdist_loader_options: list[str] = field(default_factory=list)
    xdist_workers: int | None = None
    coverage_mode: CoverageMode = CoverageMode.PRIVATE
    exclude_patterns: list[str] = field(default_factory=list)
    strict_pardons: bool = False
    audit_pardons: bool = False
    max_pardons_pct: float | None = None
    max_pardons: int | None = None
    no_coverage_filter: bool = False
    test_name_to_node_ids: dict[str, list[str]] = field(default_factory=dict)
    unmapped_selections: dict[str, list[str]] = field(default_factory=dict)
    terminal_notices: list[str] = field(default_factory=list)
    skipped_files: dict[str, str] = field(default_factory=dict)
    unrunnable_gremlin_ids: set[str] = field(default_factory=set)
    explain_gremlin_id: str | None = None
    preserved_addopts: str = ''
    doctest_ini_overrides: list[str] = field(default_factory=list)
    rerun_options: list[str] = field(default_factory=list)
    pytest_cov_options: list[str] = field(default_factory=list)
    rerun_ini_warnings: list[str] = field(default_factory=list)
    baseline_rerun_test_ids: set[str] = field(default_factory=set)
    coverage_timeout: int = DEFAULT_COVERAGE_TIMEOUT_SECONDS
    coverage_attempt_timeout: int | None = None
    mutant_timeout: int = DEFAULT_MUTANT_TIMEOUT_SECONDS
    mutant_attempt_timeout: int | None = None
    rerun_budget: RerunBudget = NO_RERUNS
    rerun_backoff_factor: float = 1.0
    rerun_cache_settings: str = ''
    collection_errors: int = 0
    baseline_aborted: bool = False
    baseline_failed_test_ids: set[str] = field(default_factory=set)


_gremlin_session: GremlinSession | None = None
_displaced_session_key = pytest.StashKey[GremlinSession | None]()
_own_session_key = pytest.StashKey[GremlinSession]()
_configured_configs: list[pytest.Config] = []


def _extract_test_name_from_context(context: str) -> str:
    """Extract the test identifier from a coverage dynamic context string.

    Handles two context formats:

    - **New format** (GremlinContextPlugin): ``{nodeid}|{when}``
      e.g. ``tests/test_foo.py::TestClass::test_bar|run``
      Returns the full node ID (everything before the *last* ``|``),
      preserving the file path and class qualifiers so that tests with the
      same function name in different files are distinguishable.  The split
      uses ``rsplit`` so that parametrize values containing ``|`` (e.g.
      ``test_add[a|b]|run``) are preserved intact.

    - **Old format** (coverage dynamic_context=test_function):
      e.g. ``test_bar`` or ``TestClass.test_method``
      Returns the value as-is (no ``|`` present, no transformation).

    Args:
        context: The raw context string from the coverage database.

    Returns:
        The full node ID for new-format contexts, or the original value
        for old-format contexts.

    Examples:
        >>> _extract_test_name_from_context('tests/test_foo.py::test_bar|run')
        'tests/test_foo.py::test_bar'
        >>> _extract_test_name_from_context('tests/test_foo.py::test_bar|setup')
        'tests/test_foo.py::test_bar'
        >>> _extract_test_name_from_context('tests/test_foo.py::TestFoo::test_bar|run')
        'tests/test_foo.py::TestFoo::test_bar'
        >>> _extract_test_name_from_context('test_bar')
        'test_bar'
        >>> _extract_test_name_from_context('TestClass.test_method')
        'TestClass.test_method'
        >>> _extract_test_name_from_context('tests/test_foo.py::test_func')
        'tests/test_foo.py::test_func'
        >>> _extract_test_name_from_context('tests/test_foo.py::test_add[a|b]|run')
        'tests/test_foo.py::test_add[a|b]'
    """
    if '|' in context:
        return context.rsplit('|', maxsplit=1)[0]
    return context


def _entry_point_warner(config: pytest.Config) -> collections.abc.Callable[[str], None]:
    """Return a warning sink for operator entry points that honours pytest's warning filters.

    Workers stay silent so a broken entry point is reported once, by the controller.
    """
    if _is_xdist_worker(config):
        return discard_warning
    return lambda message: config.issue_config_time_warning(GremlinEntryPointWarning(message), stacklevel=2)


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


def _install_session(config: pytest.Config, session: GremlinSession) -> None:
    """Make ``session`` the current session and the one ``config`` owns."""
    config.stash[_own_session_key] = session
    _set_session(session)


def _release_session(config: pytest.Config) -> None:
    """Clean up the session ``config`` owns and hand its place to the session it displaced.

    Configs can unconfigure in any order, so a still-configured Config that displaced this
    one's session is repointed at what this one displaced.
    """
    _configured_configs[:] = [configured for configured in _configured_configs if configured is not config]
    owned = config.stash[_own_session_key]
    displaced = config.stash[_displaced_session_key]
    for configured in _configured_configs:
        if configured.stash[_displaced_session_key] is owned:
            configured.stash[_displaced_session_key] = displaced
    _cleanup_instrumented_dir(owned.instrumented_dir)
    if owned.cache is not None:
        owned.cache.close()
    if _get_session() is owned:
        _set_session(displaced)


class _BaselineRecorder:
    """Records one Config's baseline test outcomes into the session that Config owns.

    Report hooks carry no Config, so each Config registers its own recorder: a report
    reaches only the session of the Config whose run produced it.
    """

    def __init__(self, config: pytest.Config) -> None:
        """Bind the recorder to ``config``."""
        self._config = config

    def _enabled_session(self) -> GremlinSession | None:
        gremlin_session = self._config.stash.get(_own_session_key, None)
        if gremlin_session is None or not gremlin_session.enabled:
            return None
        return gremlin_session

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        """Count failed collection reports so a broken baseline can skip mutation testing."""
        gremlin_session = self._enabled_session()
        if gremlin_session is not None and report.failed:
            gremlin_session.collection_errors += 1

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record each test that failed in any phase so the baseline gate sees real test outcomes.

        Node IDs are collected in a set because one test can fail in more than one
        phase (for example call and teardown) and must still count once.
        """
        gremlin_session = self._enabled_session()
        if gremlin_session is None:
            return
        if report.failed:
            gremlin_session.baseline_failed_test_ids.add(report.nodeid)
        elif str(report.outcome) == 'rerun':  # pytest-rerunfailures' outcome is not in pytest's Literal
            gremlin_session.baseline_rerun_test_ids.add(report.nodeid)

    def pytest_keyboard_interrupt(self, excinfo: pytest.ExceptionInfo[BaseException]) -> None:  # noqa: ARG002
        """Record that the baseline session was cut short (``pytest.exit`` or Ctrl-C).

        pytest calls this for every ``pytest.exit`` regardless of its return code, so a
        ``returncode=0`` exit is still recognised as an aborted baseline.
        """
        gremlin_session = self._enabled_session()
        if gremlin_session is not None:
            gremlin_session.baseline_aborted = True


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
        help='Group gremlins into worker tasks; does not reduce subprocesses (one per gremlin)',
    )
    group.addoption(
        '--gremlin-batch-size',
        action='store',
        type=int,
        default=None,
        dest='gremlin_batch_size',
        help='Number of gremlins per worker task in batch mode (default: 10)',
    )
    group.addoption(
        '--gremlin-coverage-timeout',
        action='store',
        type=int,
        default=None,
        dest='gremlin_coverage_timeout',
        help=(
            'Seconds the coverage pre-scan may run before coverage-guided test selection is '
            f'disabled (default: {DEFAULT_COVERAGE_TIMEOUT_SECONDS}, max: {MAX_TIMEOUT_SECONDS})'
        ),
    )
    group.addoption(
        '--gremlin-mutant-timeout',
        action='store',
        type=int,
        default=None,
        dest='gremlin_mutant_timeout',
        help=(
            "Seconds one attempt of a gremlin's test run may take before the gremlin is reported as a timeout "
            f'(default: {DEFAULT_MUTANT_TIMEOUT_SECONDS}, max: {MAX_TIMEOUT_SECONDS}). '
            'With pytest-rerunfailures active, each rerun adds another attempt plus the --reruns-delay wait: '
            f'limit * (reruns + 1) + ceil(reruns * delay) seconds, capped at {MAX_TIMEOUT_SECONDS}'
        ),
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
        default='auto',
        choices=['auto', 'subprocess', 'fork', 'inprocess'],
        dest='gremlin_executor',
        help=(
            'Execution strategy: auto (default, same as subprocess) or subprocess. '
            'fork and inprocess are disabled pending https://github.com/mikelane/pytest-gremlins/issues/532.'
        ),
    )
    group.addoption(
        '--gremlin-no-coverage-filter',
        action='store_true',
        default=False,
        dest='gremlin_no_coverage_filter',
        help='Disable coverage-guided test selection (slow but useful for debugging).',
    )
    group.addoption(
        '--gremlin-explain',
        action='store',
        default=None,
        dest='gremlin_explain',
        help=(
            'Diagnose why a gremlin survived: for the given gremlin id (e.g. g001), '
            'print the covering set, the selected list, their diff, and close-match '
            'suggestions for any dropped tests, then skip the mutation loop so pytest '
            'can finish normally.'
        ),
    )


def _init_cache(
    rootdir: Path,
    cache_enabled: bool,
    clear_cache: bool,
    operators: Sequence[GremlinOperator],
    *,
    pytester_loaded: Callable[[], bool] = lambda: False,
    xdist_loader_loaded: Callable[[], bool] = lambda: False,
) -> IncrementalCache | None:
    """Initialise the incremental cache when enabled, optionally clearing it first.

    Args:
        rootdir: Project root directory where the cache directory is created.
        cache_enabled: Whether to create a cache instance at all.
        clear_cache: Whether to wipe the cache before use.
        operators: The operators registered for the run, after conftest registration; their owning
            distributions are part of the cache key.
        pytester_loaded: Reports whether the session loads the pytester plugin; such sessions get their own key part.
        xdist_loader_loaded: Reports whether gremlin runs load xdist themselves (autoload disabled, #668); such
            sessions get their own key part.

    Returns:
        An open IncrementalCache, or None when caching is disabled.
    """
    if not cache_enabled:
        return None
    cache_dir = rootdir / '.gremlins_cache'
    cache = IncrementalCache(
        cache_dir,
        operators,
        project_root=rootdir,
        pytester_loaded=pytester_loaded,
        xdist_loader_loaded=xdist_loader_loaded,
    )
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


def _read_validated_pardon_limits(config: pytest.Config) -> tuple[float | None, int | None]:
    """Read the CLI pardon limits, exiting with a usage error when out of range.

    Args:
        config: The pytest config object.

    Returns:
        Tuple of (max_pardons_pct, max_pardons), each None if unset.
    """
    max_pardons_pct: float | None = getattr(config.option, 'gremlin_max_pardons_pct', None)
    if max_pardons_pct is not None and not (0 <= max_pardons_pct <= 100):  # noqa: PLR2004
        pytest.exit(
            f'--gremlin-max-pardons-pct must be between 0 and 100, got {max_pardons_pct!r}.',
            returncode=4,
        )

    max_pardons: int | None = getattr(config.option, 'max_pardons', None)
    if max_pardons is not None and max_pardons < 0:
        pytest.exit(
            f'--max-pardons must be >= 0, got {max_pardons!r}.',
            returncode=4,
        )
    return max_pardons_pct, max_pardons


def _resolve_target_paths(rootdir: Path, merged_config: object) -> list[Path]:
    """Resolve the source paths to mutate: configured paths, discovery, then ``src/``.

    Args:
        rootdir: The project root directory.
        merged_config: The result of merge_configs (GremlinConfig or a test mock).

    Returns:
        The existing paths to instrument.
    """
    configured_paths = getattr(merged_config, 'paths', None)
    if configured_paths:
        resolved = (
            rootdir / path_str if not Path(path_str).is_absolute() else Path(path_str) for path_str in configured_paths
        )
        return [path for path in resolved if path.exists()]

    discovered = (
        discover_source_paths(rootdir)
        or discover_by_project_name(rootdir)
        or discover_by_setup_cfg(rootdir)
        or discover_by_importlib_metadata(rootdir)
    )
    if discovered:
        return [rootdir / p for p in discovered]
    src_path = rootdir / 'src'
    if src_path.exists():
        return [src_path]
    logger.warning(
        'No source paths discovered; scanning the entire project root (%s). '
        'This may be slower and include files you did not intend to mutate. '
        'Add paths to pyproject.toml to target only your source code:\n'
        '  [tool.pytest-gremlins]\n'
        '  paths = ["src/your_package"]',
        rootdir,
    )
    return [rootdir]


_NON_RUNNING_MODE_FLAGS: tuple[tuple[str, str], ...] = (
    ('collectonly', '--collect-only'),
    ('setupplan', '--setup-plan'),
    ('setuponly', '--setup-only'),
    ('showfixtures', '--fixtures'),
    ('show_fixtures_per_test', '--fixtures-per-test'),
)


def _maybe_short_circuit_for_inactive_run(config: pytest.Config, config_warnings: list[str] | None = None) -> bool:
    """Disable the session for pytest modes that execute no tests, after configuration is validated.

    ``--collect-only``, ``--setup-plan``, ``--setup-only``, ``--fixtures`` and
    ``--fixtures-per-test`` run no tests, so there is no coverage to pre-scan and
    nothing to mutate against. Config loading and validation still run first so that
    ``pytest --gremlins --collect-only`` reports configuration errors. The skip notice
    names the triggering mode and goes to stderr so ``--collect-only -q`` node-id output
    on stdout stays machine-parseable; it is printed once, by the controller.

    Args:
        config: The pytest config object.
        config_warnings: Configuration warnings to print to stderr, since no terminal summary will carry them.

    Returns:
        True if the session was disabled and configuration should stop.
    """
    mode_flag = next((flag for dest, flag in _NON_RUNNING_MODE_FLAGS if getattr(config.option, dest, False)), None)
    if mode_flag is None:
        return False
    _install_session(config, GremlinSession(enabled=False))
    if not _is_xdist_worker(config):
        for warning in config_warnings or []:
            print(f'pytest-gremlins: warning: {warning}', file=sys.stderr)
        print(f'pytest-gremlins: {mode_flag} detected, skipping mutation testing', file=sys.stderr)
    return True


def _read_cli_timeout(config: pytest.Config, flag: str) -> int | None:
    """Return the seconds given to ``flag``, exiting with a usage error if they are outside 1..MAX."""
    dest = flag.removeprefix('--').replace('-', '_')
    cli_value: int | None = getattr(config.option, dest, None)
    if cli_value is not None and not 0 < cli_value <= MAX_TIMEOUT_SECONDS:
        pytest.exit(
            f'{flag} must be a positive integer number of seconds no greater than {MAX_TIMEOUT_SECONDS}, '
            f'got {cli_value!r}.',
            returncode=4,
        )
    return cli_value


DISABLED_EXECUTORS = ('fork', 'inprocess')
EXECUTOR_REDESIGN_ISSUE_URL = 'https://github.com/mikelane/pytest-gremlins/issues/532'


def _reject_disabled_executor(executor: str) -> None:
    """Fail at startup for executors that did not run the mutated code.

    Raises:
        pytest.UsageError: If ``executor`` is ``fork`` or ``inprocess``.
    """
    if executor in DISABLED_EXECUTORS:
        raise pytest.UsageError(
            f'pytest-gremlins: --gremlin-executor={executor} is temporarily disabled because it produced '
            'incorrect results (it did not run the mutated code). '
            'Use --gremlin-executor=subprocess (the default). '
            f'Tracking: {EXECUTOR_REDESIGN_ISSUE_URL}'
        )


# pytester registers under its entry-point name when loaded by name, and under its module path when loaded
# with ``-p _pytest.pytester`` or ``pytest_plugins = ['_pytest.pytester']`` (#891).
PYTESTER_PLUGIN_NAMES = ('pytester', '_pytest.pytester')


def _pytester_loaded(config: pytest.Config) -> bool:
    """Report whether the session loads the pytester plugin under any registration name (#891).

    Args:
        config: The pytest config whose plugin manager is asked.

    Returns:
        True when pytester is registered under any name in ``PYTESTER_PLUGIN_NAMES``.
    """
    return any(config.pluginmanager.has_plugin(name) for name in PYTESTER_PLUGIN_NAMES)


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options.

    Configuration precedence (highest to lowest):
    1. CLI arguments (--gremlin-operators, --gremlin-targets, --gremlin-exclude,
       --gremlin-workers, --gremlin-report, --gremlin-batch-size, --gremlin-cache)
    2. pyproject.toml [tool.pytest-gremlins] section
    3. Built-in defaults (all operators, src/ directory, console report, batch-size 10)
    """
    config.stash[_displaced_session_key] = _get_session()
    _configured_configs.append(config)
    _install_session(config, GremlinSession(enabled=False))
    config.pluginmanager.register(_BaselineRecorder(config))
    if not config.option.gremlins:
        return

    _reject_disabled_executor(getattr(config.option, 'gremlin_executor', 'auto'))

    # xdist with -n > 0 distributes test items across workers; gremlins runs
    # its mutation phase sequentially after xdist tears down (two-phase mode).
    # -n 0 means "no distribution" — treat it the same as xdist not present.
    xdist_numprocesses = getattr(config.option, 'numprocesses', None)
    xdist_active = xdist_numprocesses not in (None, 0)

    rootdir = _get_rootdir(config)

    cli_max_pardons_pct, cli_max_pardons = _read_validated_pardon_limits(config)

    cli_coverage_timeout = _read_cli_timeout(config, '--gremlin-coverage-timeout')
    cli_mutant_timeout = _read_cli_timeout(config, '--gremlin-mutant-timeout')

    cli_report_list = _parse_cli_report_formats(config.option.gremlin_report)

    # Entry-point operators must be registered before load_config validates operator names.
    registry = get_default_registry()
    load_entry_point_operators(registry, warn=_entry_point_warner(config))

    # Load config from pyproject.toml and merge with CLI args
    config_warnings: list[str] = []
    try:
        merged_config = merge_configs(
            load_config(
                rootdir,
                on_warning=config_warnings.append,
                warn_when_operators_empty=not (config.option.gremlin_operators or '').strip(),
            ),
            cli_operators=config.option.gremlin_operators,
            cli_targets=config.option.gremlin_targets,
            cli_exclude=config.option.gremlin_exclude,
            cli_workers=config.option.gremlin_workers,
            cli_cache=config.option.gremlin_cache or None,
            cli_report=cli_report_list,
            cli_batch_size=config.option.gremlin_batch_size,
            cli_max_pardons_pct=cli_max_pardons_pct,
            cli_max_pardons=cli_max_pardons,
            cli_coverage_timeout=cli_coverage_timeout,
            cli_mutant_timeout=cli_mutant_timeout,
        )
    except ValueError as invalid:
        raise pytest.UsageError(f'pytest-gremlins: {invalid}') from invalid

    # Use merged operators or all if none specified
    operators = registry.get_all(enabled=merged_config.operators) if merged_config.operators else registry.get_all()

    target_paths = _resolve_target_paths(rootdir, merged_config)

    if _maybe_short_circuit_for_inactive_run(config, config_warnings):
        return

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
    rerun_options = _rerun_options_for(config)
    xdist_loader_options, xdist_loaded = _xdist_options_for(config, rerun_options)
    cache: IncrementalCache | None = _init_cache(
        rootdir,
        cache_enabled,
        config.option.gremlin_clear_cache,
        operators,
        pytester_loaded=lambda: _pytester_loaded(config),
        xdist_loader_loaded=lambda: bool(xdist_loader_options),
    )

    xdist_worker_int: int | None = xdist_numprocesses if isinstance(xdist_numprocesses, int) else None
    xdist_workers_for_parallel = xdist_worker_int if xdist_active else None
    parallel_enabled, parallel_workers = _read_parallel_config(config, xdist_workers=xdist_workers_for_parallel)
    merged_workers = toml_workers if isinstance(toml_workers, int) else None
    if parallel_workers is None and merged_workers is not None:
        parallel_workers = merged_workers
        parallel_enabled = True

    # Batch and report: merge_configs already resolved CLI-beats-TOML
    batch_enabled = config.option.gremlin_batch
    batch_size: int = toml_batch_size if toml_batch_size is not None else DEFAULT_BATCH_SIZE
    coverage_timeout = merged_config.coverage_timeout or DEFAULT_COVERAGE_TIMEOUT_SECONDS
    mutant_attempt_timeout = merged_config.mutant_timeout or DEFAULT_MUTANT_TIMEOUT_SECONDS
    report_formats: list[str] = toml_report if toml_report is not None else list(DEFAULT_REPORT_FORMATS)

    _install_session(
        config,
        GremlinSession(
            enabled=True,
            terminal_notices=[f'pytest-gremlins: warning: {warning}' for warning in config_warnings],
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
            no_coverage_filter=bool(getattr(config.option, 'gremlin_no_coverage_filter', False)),
            explain_gremlin_id=getattr(config.option, 'gremlin_explain', None),
            xdist_active=xdist_active,
            xdist_loaded=xdist_loaded,
            xdist_loader_options=xdist_loader_options,
            xdist_workers=xdist_worker_int if xdist_active else None,
            preserved_addopts=_addopts_for_gremlin_runs(config),
            doctest_ini_overrides=_doctest_ini_overrides(config),
            rerun_options=rerun_options,
            pytest_cov_options=_pytest_cov_options_for(config, rerun_options),
            rerun_ini_warnings=_rerun_ini_warnings_for(config),
            coverage_timeout=_rerun_scaled_timeout(config, coverage_timeout, label='Coverage pre-scan'),
            coverage_attempt_timeout=coverage_timeout,
            mutant_timeout=_rerun_scaled_timeout(config, mutant_attempt_timeout, label='Mutant'),
            mutant_attempt_timeout=mutant_attempt_timeout,
            rerun_budget=_gremlin_run_rerun_budget(config),
            rerun_backoff_factor=_gremlin_run_rerun_backoff_factor(config),
            rerun_cache_settings=_gremlin_run_rerun_cache_settings(config),
        ),
    )


def _is_running_on_sysmon(cov: coverage.Coverage) -> bool:
    """Report whether ``cov`` measures with coverage's sysmon core.

    sysmon ignores contexts set through ``switch_context`` (and warns about it
    since coverage 7.15.3), so attaching ``GremlinContextPlugin`` would be useless
    and, under ``filterwarnings = error``, fatal. Uses the public ``sys_info()``,
    which reports the core of a started instance.

    Args:
        cov: The coverage instance pytest-cov is measuring with.

    Returns:
        True only when the core is positively identified as sysmon; a failed probe
        returns False so the context plugin is still attached.
    """
    try:
        return dict(cov.sys_info()).get('core') == 'SysMonitor'
    except (TypeError, ValueError, CoverageException):
        return False


def pytest_sessionstart(session: pytest.Session) -> None:
    """At session start, register GremlinContextPlugin for coverage context tracking.

    In PIGGYBACK mode (``--cov`` is active), attaches a
    :class:`~pytest_gremlins.coverage.context_plugin.GremlinContextPlugin`
    to the pytest-cov coverage instance so that every test phase is tagged
    with ``{nodeid}|{when}`` in the coverage database.

    In PRIVATE mode nothing is registered: the pre-scan subprocess collects the
    coverage that gremlins reads, so no inline instance is needed.

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
        if _is_running_on_sysmon(cov_instance):
            logger.debug('pytest-cov coverage runs on sysmon; skipping per-test context switching')
            return
        context_plugin = GremlinContextPlugin(cov_instance)
        session.config.pluginmanager.register(context_plugin)


if _XDIST_AVAILABLE:

    @pytest.hookimpl(optionalhook=True)
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


def _is_gremlin_finder(finder: object) -> bool:
    """Report whether a ``sys.meta_path`` entry is a gremlin finder; a hostile ``__getattr__`` counts as no."""
    try:
        return bool(getattr(finder, 'is_gremlin_finder', False))
    except Exception:
        return False


@pytest.hookimpl(hookwrapper=True)
def pytest_load_initial_conftests() -> collections.abc.Generator[None, None, None]:
    """Keep an installed gremlin finder ahead of the assertion-rewrite hook this session just installed.

    An in-process pytester session (``runpytest()``, ``inline_run()``) runs ``pytest.main`` inside a gremlin
    subprocess; its rewrite hook lands at the front of ``sys.meta_path`` and would serve, uninstrumented, every
    target it claims that is first imported in that session (#615).
    """
    for finder in [finder for finder in sys.meta_path if _is_gremlin_finder(finder)]:
        sys.meta_path.remove(finder)
        sys.meta_path.insert(0, finder)
    yield


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
    if session.items and _rerunfailures_is_loaded(session.config):
        gremlin_session.mutant_timeout = mutant_timeout_for_items(
            gremlin_session.mutant_attempt_timeout or gremlin_session.mutant_timeout,
            gremlin_session.mutant_timeout,
            session.items,
        )

    # Normalize node IDs for subprocess execution.
    # In some contexts (e.g. pytester) node IDs can include absolute paths, and
    # some plugins (e.g. pytest-test-categories) add display suffixes like
    # "[SMALL]" which are not valid when passed back to pytest.
    rootdir = _get_rootdir(session.config)
    node_ids = [item.nodeid for item in session.items]
    normalized_node_ids = _make_node_ids_relative(node_ids, rootdir)
    gremlin_session.test_node_ids = {node_id: node_id for node_id in normalized_node_ids}

    name_to_nodes: dict[str, list[str]] = {}
    for node_id in normalized_node_ids:
        func_name = node_id.split('::')[-1]
        name_to_nodes.setdefault(func_name, []).append(node_id)
    gremlin_session.test_name_to_node_ids = name_to_nodes

    source_files = _discover_source_files(session, gremlin_session)
    gremlin_session.source_files = source_files

    _hash_sources_and_tests_for_cache(
        gremlin_session,
        source_files,
        rootdir,
        _test_file_patterns(gremlin_session, session.config),
        _pythonpath_entries(gremlin_session, session.config),
    )

    if gremlin_session.xdist_active and not session.items:
        logger.debug(
            'pytest_collection_finish: xdist controller has zero items; '
            'deferring gremlin generation to pytest_sessionfinish'
        )
        return

    _generate_gremlins(gremlin_session, source_files, rootdir)


def _hash_sources_and_tests_for_cache(
    gremlin_session: GremlinSession,
    source_files: dict[str, str],
    rootdir: Path,
    test_file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
    pythonpath: tuple[Path, ...] = (),
) -> None:
    """Record content hashes of the source and test files that key the incremental cache.

    Without these hashes the cache can neither store nor replay a verdict, so every gremlin runs again.
    Test hashes are keyed by the file part of the normalized node ids, so a test binds to its own file's
    hash by exact lookup and the keys are the same with or without xdist. ``test_file_patterns`` are the
    ``python_files`` globs that tell a test file from a helper; ``pythonpath`` holds the directories the ini
    ``pythonpath`` setting puts on ``sys.path``, where an import can resolve.
    """
    if not gremlin_session.cache_enabled:
        return
    hasher = ContentHasher()
    for file_path, source in source_files.items():
        gremlin_session.source_hashes[file_path] = hasher.hash_string(source)
    test_files = {node_id.split('::')[0] for node_id in gremlin_session.test_node_ids}
    memo = _KeyMemo(pythonpath=tuple(Path(os.path.normpath(entry)) for entry in pythonpath))
    for test_file in test_files:
        # A file part pytest left empty (a test outside rootdir) cannot say which file the test lives in.
        if test_file and (rootdir / test_file).is_file():
            gremlin_session.test_hashes[test_file] = _hash_test_file_with_conftests(
                hasher, rootdir, test_file, test_file_patterns, memo
            )


def _test_file_patterns(gremlin_session: GremlinSession, config: pytest.Config) -> tuple[str, ...]:
    """Return the ``python_files`` globs pytest uses to collect test files; only the cache key needs them."""
    if not gremlin_session.cache_enabled:
        return DEFAULT_TEST_FILE_PATTERNS
    configured = config.getini('python_files')
    return tuple(configured) if configured else DEFAULT_TEST_FILE_PATTERNS


def _pythonpath_entries(gremlin_session: GremlinSession, config: pytest.Config) -> tuple[Path, ...]:
    """Return the ini ``pythonpath`` directories, resolved against rootdir; only the cache key needs them."""
    if not gremlin_session.cache_enabled:
        return ()
    return tuple(config.rootpath / entry for entry in config.getini('pythonpath'))


@dataclass
class _KeyMemo:
    """Per-run memo: each test root is swept once, each file is parsed and hashed once, each import resolved once."""

    pythonpath: tuple[Path, ...] = ()
    helper_parts_by_sweep: dict[tuple[Path, bool], list[str]] = field(default_factory=dict)
    import_targets_by_file: dict[Path, frozenset[Path]] = field(default_factory=dict)
    import_targets_under_root: dict[tuple[Path, Path], frozenset[Path]] = field(default_factory=dict)
    reachable_from: dict[tuple[Path, Path], frozenset[Path]] = field(default_factory=dict)
    test_file_names: dict[Path, bool] = field(default_factory=dict)
    module_files: dict[tuple[Path, tuple[str, ...], int], tuple[Path, ...]] = field(default_factory=dict)
    directories_to_rootdir: dict[Path, tuple[Path, ...]] = field(default_factory=dict)
    conftests_by_directory: dict[Path, tuple[Path, ...]] = field(default_factory=dict)
    file_hashes: dict[Path, str] = field(default_factory=dict)
    hash_parts: dict[Path, str] = field(default_factory=dict)


def _file_hash(hasher: ContentHasher, path: Path, memo: _KeyMemo) -> str:
    if path not in memo.file_hashes:
        memo.file_hashes[path] = hasher.hash_file(path)
    return memo.file_hashes[path]


def _hash_part(hasher: ContentHasher, rootdir: Path, path: Path, memo: _KeyMemo) -> str:
    if path not in memo.hash_parts:
        memo.hash_parts[path] = f'{path.relative_to(rootdir).as_posix()}:{_file_hash(hasher, path, memo)}'
    return memo.hash_parts[path]


def _directories_to_rootdir(rootdir: Path, directory: Path, memo: _KeyMemo) -> tuple[Path, ...]:
    """Return ``directory`` and each parent up to rootdir, nearest first; empty when it is outside rootdir."""
    if directory not in memo.directories_to_rootdir:
        chain: list[Path] = []
        if directory.is_relative_to(rootdir):
            current = directory
            while current != rootdir:
                chain.append(current)
                current = current.parent
            chain.append(rootdir)
        memo.directories_to_rootdir[directory] = tuple(chain)
    return memo.directories_to_rootdir[directory]


def _conftests_on_path(rootdir: Path, directory: Path, memo: _KeyMemo) -> tuple[Path, ...]:
    if directory not in memo.conftests_by_directory:
        candidates = (d / 'conftest.py' for d in _directories_to_rootdir(rootdir, directory, memo))
        memo.conftests_by_directory[directory] = tuple(path for path in candidates if path.is_file())
    return memo.conftests_by_directory[directory]


def _hash_test_file_with_conftests(
    hasher: ContentHasher,
    rootdir: Path,
    test_file: str,
    test_file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
    memo: _KeyMemo | None = None,
) -> str:
    """Hash a test file with its conftests, the helper modules in its test root and the test files it imports.

    A fixture edited in a conftest changes what the test does, so it must change the key (#702). So does an edit
    to a helper module the test or a conftest imports (#760), or to another test file they import (#910).
    ``memo`` lets a run read each test root once, not once per test file.
    """
    memo = memo if memo is not None else _KeyMemo()
    test_path = rootdir / test_file
    parts = [_file_hash(hasher, test_path, memo)]
    conftests = _conftests_on_path(rootdir, test_path.parent, memo)
    parts.extend(_hash_part(hasher, rootdir, conftest, memo) for conftest in conftests)
    sweep = _helper_sweep(rootdir, test_file)
    if sweep not in memo.helper_parts_by_sweep:
        memo.helper_parts_by_sweep[sweep] = _helper_module_hash_parts(hasher, rootdir, sweep, test_file_patterns)
    parts.extend(memo.helper_parts_by_sweep[sweep])
    imported = _imported_test_files(rootdir, sweep[0], [test_path, *conftests], test_file_patterns, memo)
    parts.extend(sorted(_hash_part(hasher, rootdir, path, memo) for path in imported - {test_path}))
    return hasher.hash_string('|'.join(parts)) if len(parts) > 1 else parts[0]


def _helper_sweep(rootdir: Path, test_file: str) -> tuple[Path, bool]:
    """Return the directory to sweep for helpers and whether to recurse into it.

    The test root is the top-level directory under rootdir that holds the test file. A test file that sits
    directly in rootdir, or a rootdir that is the filesystem root, has no safe directory to sweep recursively,
    so the test file's own directory is read without recursing.
    """
    parts = Path(test_file).parts
    if len(parts) > 1 and rootdir != rootdir.parent:
        return rootdir / parts[0], True
    return (rootdir / test_file).parent, False


def _helper_module_hash_parts(
    hasher: ContentHasher, rootdir: Path, sweep: tuple[Path, bool], test_file_patterns: tuple[str, ...]
) -> list[str]:
    """Hash every helper ``.py`` file in the swept directory, in sorted path order (#760).

    A ``pytest_plugins`` module or a helper a test or conftest imports is not named by the test file, so the
    coarse rule hashes every helper there: an edit re-runs gremlins for every test file under that root, never
    replays a stale verdict. A helper is any Python file whose name matches no ``python_files`` pattern, that is
    not a ``conftest.py`` and is not under ``__pycache__``. Which files pytest collected in this run decides
    nothing (#910); test files reach a key only through the imports that name them.
    """
    directory, recursive = sweep
    candidates = directory.rglob('*.py') if recursive else directory.glob('*.py')
    helpers = sorted(path for path in candidates if path.is_file() and _is_helper_module(path, test_file_patterns))
    return [f'{path.relative_to(rootdir).as_posix()}:{hasher.hash_file(path)}' for path in helpers]


def _is_test_file_name(path: Path, test_file_patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in test_file_patterns)


def _is_helper_module(path: Path, test_file_patterns: tuple[str, ...]) -> bool:
    return (
        not _is_test_file_name(path, test_file_patterns)
        and path.name != 'conftest.py'
        and '__pycache__' not in path.parts
    )


def _imported_test_files(
    rootdir: Path,
    test_root: Path,
    entry_points: list[Path],
    test_file_patterns: tuple[str, ...],
    memo: _KeyMemo,
) -> frozenset[Path]:
    """Return the test files reachable from ``entry_points`` through static imports under ``test_root`` (#910).

    Imports that only run at call time (``importlib.import_module`` with a computed name) are not followed.
    """
    reachable: set[Path] = set()
    for entry_point in entry_points:
        reachable |= _reachable_from(rootdir, test_root, entry_point, memo)
    return frozenset(path for path in reachable if _is_known_test_file(path, test_file_patterns, memo))


def _reachable_from(rootdir: Path, test_root: Path, start: Path, memo: _KeyMemo) -> frozenset[Path]:
    """Return ``start`` and every file it reaches through imports under ``test_root``.

    A file whose own reach is already known contributes it whole, so a long import chain is walked once.
    """
    key = (start, test_root)
    if key not in memo.reachable_from:
        visited: set[Path] = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            for target in _import_targets_under(rootdir, test_root, current, memo):
                if target in visited:
                    continue
                known = memo.reachable_from.get((target, test_root))
                if known is None:
                    visited.add(target)
                    pending.append(target)
                else:
                    visited |= known
        memo.reachable_from[key] = frozenset(visited)
    return memo.reachable_from[key]


def _is_known_test_file(path: Path, test_file_patterns: tuple[str, ...], memo: _KeyMemo) -> bool:
    if path not in memo.test_file_names:
        memo.test_file_names[path] = _is_test_file_name(path, test_file_patterns)
    return memo.test_file_names[path]


def _import_targets_under(rootdir: Path, test_root: Path, path: Path, memo: _KeyMemo) -> frozenset[Path]:
    key = (path, test_root)
    if key not in memo.import_targets_under_root:
        memo.import_targets_under_root[key] = frozenset(
            target for target in _import_targets(rootdir, path, memo) if target.is_relative_to(test_root)
        )
    return memo.import_targets_under_root[key]


def _import_targets(rootdir: Path, path: Path, memo: _KeyMemo) -> frozenset[Path]:
    if path not in memo.import_targets_by_file:
        memo.import_targets_by_file[path] = frozenset(_parse_import_targets(rootdir, path, memo))
    return memo.import_targets_by_file[path]


def _parse_import_targets(rootdir: Path, path: Path, memo: _KeyMemo) -> set[Path]:
    """Resolve every import in ``path`` to the ``.py`` files it names; unreadable source yields none.

    A string in a module-level ``pytest_plugins`` assignment names a module pytest imports, so it counts as an
    import. Parsing the raw bytes lets ``ast`` honor a BOM or a ``coding:`` declaration.
    """
    try:
        tree = ast.parse(path.read_bytes())
    except (SyntaxError, OSError, ValueError):
        return set()
    targets: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.update(_module_files(rootdir, path, alias.name.split('.'), 0, memo))
        elif isinstance(node, ast.ImportFrom):
            module = node.module.split('.') if node.module else []
            targets.update(_module_files(rootdir, path, module, node.level, memo))
            for alias in node.names:
                targets.update(_module_files(rootdir, path, [*module, alias.name], node.level, memo))
    for plugin_module in _pytest_plugins_modules(tree):
        targets.update(_module_files(rootdir, path, plugin_module.split('.'), 0, memo))
    return targets


def _module_level_statements(body: list[ast.stmt]) -> collections.abc.Iterator[ast.stmt]:
    """Yield the statements that run at import time: the module body and the blocks ``try`` and ``if`` nest in it."""
    for statement in body:
        yield statement
        if isinstance(statement, ast.If):
            yield from _module_level_statements(statement.body)
            yield from _module_level_statements(statement.orelse)
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            yield from _module_level_statements(statement.body)
            for handler in statement.handlers:
                yield from _module_level_statements(handler.body)
            yield from _module_level_statements(statement.orelse)
            yield from _module_level_statements(statement.finalbody)


def _pytest_plugins_modules(tree: ast.Module) -> list[str]:
    """Return the module names in a module-level ``pytest_plugins = 'x'`` or ``['x', 'y']`` assignment."""
    names: list[str] = []
    for statement in _module_level_statements(tree.body):
        if isinstance(statement, ast.Assign):
            assigns_plugins = any(isinstance(t, ast.Name) and t.id == 'pytest_plugins' for t in statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            assigns_plugins = isinstance(statement.target, ast.Name) and statement.target.id == 'pytest_plugins'
        else:
            continue
        value = statement.value
        if assigns_plugins and value is not None:
            elements = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
            names.extend(e.value for e in elements if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return names


def _module_files(rootdir: Path, importer: Path, module: list[str], level: int, memo: _KeyMemo) -> tuple[Path, ...]:
    """Return the existing files a dotted module path can name, looked up from where Python could start.

    A relative import starts at the importer's package. An absolute one may start at rootdir, at any directory
    between the importer and rootdir (pytest puts a test file's own directory on ``sys.path``) or at an ini
    ``pythonpath`` entry. Answers are memoized per importer directory, so a directory of test files resolves
    each import once.
    """
    if not module:
        return ()
    key = (importer.parent, tuple(module), level)
    if key not in memo.module_files:
        if level:
            ancestors = [importer.parent, *importer.parent.parents]
            bases: list[Path] = ancestors[level - 1 : level]
        else:
            bases = [*_directories_to_rootdir(rootdir, importer.parent, memo), *memo.pythonpath]
        stems = [base.joinpath(*module) for base in bases]
        candidates = [candidate for stem in stems for candidate in (stem.with_suffix('.py'), stem / '__init__.py')]
        memo.module_files[key] = tuple(candidate for candidate in candidates if _is_file(candidate))
    return memo.module_files[key]


def _is_file(candidate: Path) -> bool:
    """Return whether ``candidate`` is a file; a path Python's import system cannot probe is not one."""
    try:
        return candidate.is_file()
    except OSError:
        return False


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

    targets, duplicates = _without_duplicate_origins(source_files, rootdir)
    for file_path in targets:
        source = source_files[file_path]
        try:
            gremlins, instrumented_tree = transform_source(source, file_path, gremlin_session.operators)
        except Exception as exc:
            logger.exception('Failed to transform %s; skipping file', file_path)
            reason = _describe_exception(exc)
            gremlin_session.skipped_files[file_path] = reason
            displayed_path = _neutralize_control_characters(file_path)
            _queue_terminal_notice(
                gremlin_session, f'pytest-gremlins: skipped {displayed_path}: could not instrument ({reason})'
            )
            continue
        all_gremlins.extend(gremlins)
        instrumented_asts[file_path] = instrumented_tree

    gremlin_session.gremlins = all_gremlins

    if all_gremlins:
        instrumented_dir = _write_instrumented_sources(instrumented_asts, rootdir, duplicates)
        gremlin_session.instrumented_dir = instrumented_dir


def _neutralize_control_characters(text: str) -> str:
    """Replace control characters (such as ESC) so untrusted text cannot drive the terminal."""
    return ''.join(char if char.isprintable() else '?' for char in text)


def _describe_exception(exc: BaseException) -> str:
    """Render an exception as ``Type: message`` on one line, or just ``Type`` when it has no message."""
    try:
        raw_message = str(exc)
    except Exception:
        raw_message = ''
    message = _neutralize_control_characters(' '.join(raw_message.split()))
    return f'{type(exc).__name__}: {message}' if message else type(exc).__name__


def _queue_terminal_notice(gremlin_session: GremlinSession, message: str) -> None:
    """Queue a line for the terminal summary, once per distinct message."""
    if message not in gremlin_session.terminal_notices:
        gremlin_session.terminal_notices.append(message)


def _spelling_rank(file_path: str, rootdir: Path) -> tuple[bool, str]:
    """Rank a target so that a real file outranks a symlink to it, then by path."""
    origin = (rootdir / file_path).absolute()
    return (str(origin) != os.path.realpath(origin), file_path)


def _without_duplicate_origins(source_files: dict[str, str], rootdir: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Return the targets in a stable order with each file on disk listed once.

    The finder in the test subprocess matches a file by where it really is, so two targets that are one
    file (a symlink, a hard link) can only be served one instrumented source: the loser's gremlins would
    never activate and be reported as survivors. A loser is dropped before it generates gremlins, and the
    drop is logged with the file it duplicates.

    Args:
        source_files: Mapping of target paths to their source code.
        rootdir: Root directory of the project; a relative path is taken from it.

    Returns:
        The target paths to instrument, real files first, then in path order, and for each of them the
        other spellings of the same file that were dropped.
    """
    kept: list[str] = []
    duplicates: dict[str, list[str]] = {}
    first_seen: dict[str, str] = {}
    for file_path in sorted(source_files, key=lambda path: _spelling_rank(path, rootdir)):
        origin = str((rootdir / file_path).absolute())
        identity = file_identity(origin) or normalize_origin(origin)
        if identity in first_seen:
            logger.warning(
                'Skipping %s as a mutation target: it is the same file on disk as %s, '
                'so its gremlins are generated once under that path and stay active when imported through either. '
                'List only one of them in the gremlin targets to silence this warning',
                file_path,
                first_seen[identity],
            )
            duplicates[first_seen[identity]].append(file_path)
            continue
        first_seen[identity] = file_path
        duplicates[file_path] = []
        kept.append(file_path)
    return kept, duplicates


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
        # tokenize.open honors PEP 263 coding declarations and strips BOM
        with tokenize.open(str(path)) as source_stream:
            source = source_stream.read()
        ast.parse(source)
        source_files[str(path)] = source
    except SyntaxError:
        logger.debug('Skipping %s: syntax error', path)
    except (OSError, UnicodeDecodeError, LookupError) as exc:
        logger.debug('Skipping %s: %s', path, exc)


def _write_instrumented_sources(
    instrumented_asts: dict[str, ast.Module],
    rootdir: Path,
    duplicates: dict[str, list[str]] | None = None,
) -> Path:
    """Write instrumented sources to a JSON file for import hook injection.

    Creates a temporary directory containing:
    1. A JSON file mapping the normalized real path of each instrumented file to its
       instrumented tree (``tree``: the instrumented AST, pickled, zlib compressed and base64 encoded for the subprocess
       to compile under the real file path; absent when the tree is too deep to pickle), its unparsed text
       (``source``: always present, what the subprocess compiles when the tree is absent or too deep), the
       path it came from, the file's device and inode (``identity``, for spellings the path key misses) and
       the lowercased file names it may be imported as (``names``, so the finder skips every other import
       without touching the disk). No module name is recorded: the finder in the
       subprocess serves a file under whatever name the import system resolves to it.
    2. A bootstrap script that registers import hooks and runs pytest
    3. A ``spawn_hook`` directory holding a ``sitecustomize.py`` that installs the same finder in fresh
       interpreters, such as ``multiprocessing`` spawn children (#604)

    This approach ensures that import hooks are registered BEFORE any modules
    are imported, which is necessary because pytest adds the test directory
    to sys.path before PYTHONPATH.

    Args:
        instrumented_asts: Mapping of original file paths to their instrumented ASTs.
        rootdir: Root directory of the project; a relative path is taken from it.
        duplicates: For a path in ``instrumented_asts``, the other spellings of the same file that
            were dropped as targets; imported through one of them, the file is still served.

    Returns:
        Path to the temporary directory containing the bootstrap infrastructure.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix='pytest_gremlins_'))

    instrumented_sources: origin_finder.InstrumentedSources = {}
    for original_path, tree in instrumented_asts.items():
        origin = (rootdir / original_path).absolute()
        instrumented_tree = _inject_gremlin_active(tree)
        encoded_tree = _encode_tree(instrumented_tree)
        if encoded_tree is None:
            logger.debug(
                'Instrumented tree for %s too deep to pickle; shipping unparsed source (reflowed line numbers)',
                origin,
            )
        spellings = [str(origin), os.path.realpath(origin), *(duplicates or {}).get(original_path, [])]
        entry = origin_finder.InstrumentedEntry(
            source=ast.unparse(instrumented_tree),
            origin=str(origin),
            identity=file_identity(str(origin)),
            file_names=sorted({Path(spelling).name.lower() for spelling in spellings}),
        )
        if encoded_tree is not None:
            entry['tree'] = encoded_tree
        instrumented_sources[normalize_origin(str(origin))] = entry

    sources_file = temp_dir / 'sources.json'
    sources_file.write_text(json.dumps(instrumented_sources))

    bootstrap_script = temp_dir / 'gremlin_bootstrap.py'
    bootstrap_script.write_text(_get_bootstrap_script())
    write_spawn_hook(temp_dir)

    # The lightweight runner is deliberately not written: it cannot reproduce pytest's conftest,
    # configure hooks or sys.path, so every gremlin runs through the bootstrap (#538).

    return temp_dir


def _inject_gremlin_active(tree: ast.Module) -> ast.Module:
    """Return ``tree`` with the ``__gremlin_active__`` assignment placed where the module may legally hold it."""
    activation_source = f"""import os as _gremlin_os
__gremlin_active__ = _gremlin_os.environ.get('{ACTIVE_GREMLIN_ENV_VAR}')
del _gremlin_os
"""
    header = ast.parse(activation_source).body
    body = _prepend_injection(tree.body, header)
    _relocate_to_next_statement(header, body)
    return ast.Module(body=body, type_ignores=tree.type_ignores)


def _relocate_to_next_statement(header: list[ast.stmt], body: list[ast.stmt]) -> None:
    """Move the injected ``header`` off the target file's real lines, in place.

    The header is parsed from its own three-line text, so its nodes would claim lines 1 to 3 and columns of the
    target file. Were ``os.environ.get`` to raise during import, the traceback would point at those real lines and
    underline unrelated text. The header takes the line of the statement that follows it; with none following, the
    line after the last statement before it (line 1 for an empty module). Its columns are zeroed, so no carets
    are drawn.
    """
    first_index = body.index(header[0])
    following_index = first_index + len(header)
    if following_index < len(body):
        line = body[following_index].lineno
    elif first_index:
        line = (body[first_index - 1].end_lineno or body[first_index - 1].lineno) + 1
    else:
        line = 1
    for node in (descendant for statement in header for descendant in ast.walk(statement)):
        if isinstance(node, (ast.stmt, ast.expr)):
            node.lineno = node.end_lineno = line
            node.col_offset = node.end_col_offset = 0


def _encode_tree(instrumented_tree: ast.Module) -> str | None:
    """Return ``instrumented_tree`` pickled, zlib compressed and base64 encoded, or ``None`` if nested too deeply.

    The subprocess compiles the tree itself, under the real file path, so the original line numbers survive and
    the subprocess's own optimize level and warning filters apply. Pickling recurses once per level of nesting,
    bounded by the recursion limit (about 250 ``elif`` branches reach it on Python 3.11; on 3.12 and later
    pickling goes much less deep per level and only fails at roughly 2,500 branches), so a ``RecursionError``
    here means the file is shipped as its unparsed ``source`` alone, with the reflowed line numbers of the
    releases before #563.
    """
    try:
        return base64.b64encode(zlib.compress(pickle.dumps(ast.fix_missing_locations(instrumented_tree)))).decode(
            'ascii'
        )
    except RecursionError:
        return None


def _prepend_injection(body: list[ast.stmt], injection_nodes: list[ast.stmt]) -> list[ast.stmt]:
    """Insert injection nodes after any module docstring and future imports.

    Python requires that ``from __future__`` imports appear before all other
    statements (except the module docstring).  Placing the gremlin activation
    code first would violate this rule when the source already contains a
    ``from __future__`` import, causing a ``SyntaxError`` at compile time.
    This function inserts the injection at the AST level so
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
    script = """#!/usr/bin/env python
'''Bootstrap script for pytest-gremlins mutation testing.

This script registers import hooks to intercept module imports and provide
instrumented code with mutation switching logic, then runs pytest.
'''

import json
import os
import sys
import traceback

__ORIGIN_FINDER_SOURCE__

__NODE_ID_ARGS_SOURCE__


def main():
    sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE')
    if not sources_file:
        print('Error: PYTEST_GREMLINS_SOURCES_FILE not set', file=sys.stderr)
        sys.exit(__USAGE_ERROR_EXIT_CODE__)

    with open(sources_file, encoding='utf-8') as f:
        instrumented_sources = json.load(f)

    # Serve each instrumented file under whatever name the import system resolves it to.
    finder = install(instrumented_sources)

    # Now run pytest with remaining arguments. pytest is imported only now: its own imports (pluggy,
    # iniconfig, pygments) must be served by the finder installed above, or a project mutating one of
    # them would run unmutated.
    import pytest
    from _pytest.config import ConftestImportFailure

    class FinderFronter:
        # pytest parses its command line, which puts its assertion-rewrite hook at the front of
        # sys.meta_path, ahead of our finder, so the hook would serve (and we would never instrument)
        # every conftest.py and python_files match. Re-front the finder after the hook exists but before
        # any conftest or test module is imported. The loader still applies pytest's assertion rewriting to
        # what the hook would have served. Plugins loaded earlier (-p, entry points) are already imported
        # and stay uninstrumented.
        @pytest.hookimpl(hookwrapper=True)
        def pytest_load_initial_conftests(self, early_config, parser, args):
            if finder in sys.meta_path:
                sys.meta_path.remove(finder)
                sys.meta_path.insert(0, finder)
            yield

    class SuiteLoadRecorder:
        # Records, in-process, that the suite could not be loaded. pytest reports an
        # unloadable suite with exit code 2 or 4, and our own bad arguments with 4 too,
        # so the exit code alone cannot tell a mutant-caused failure from our bug.
        def __init__(self):
            self.suite_failed_to_load = False

        @pytest.hookimpl(hookwrapper=True)
        def pytest_load_initial_conftests(self, early_config, parser, args):
            outcome = yield
            if outcome.excinfo is not None and issubclass(outcome.excinfo[0], ConftestImportFailure):
                self.suite_failed_to_load = True

        def pytest_collectreport(self, report):
            if report.failed:
                self.suite_failed_to_load = True

        @pytest.hookimpl(hookwrapper=True)
        def pytest_collection(self, session):
            outcome = yield
            if outcome.excinfo is None or not issubclass(outcome.excinfo[0], pytest.UsageError):
                return
            # A requested node id that is not found (for example a changed parametrize id) is the
            # mutant's doing, but only if the file it names still exists. A missing file is ours.
            if all(os.path.exists(argument.split('::')[0]) for argument in session.config.args):
                self.suite_failed_to_load = True

    # The parent writes this marker when its unmutated control run could not load the suite here,
    # in which case a load failure says nothing about the mutant and must stay a plain pytest error.
    marker = os.path.join(os.path.dirname(sources_file), '__UNATTRIBUTABLE_MARKER__')
    can_attribute_load_failures = not os.path.exists(marker)

    # The parent keeps node ids off the command line (Windows caps it at 32,767 characters) and names a
    # file holding them; pytest receives the same arguments it would with the ids appended to argv. A file
    # that cannot be read exits with pytest's usage error code, never 1, which would score as a kill.
    try:
        pytest_args = args_with_node_ids_from_file(sys.argv[1:])
    except (OSError, ValueError, RecursionError, MemoryError) as error:
        print(f'pytest-gremlins: cannot read the node ids file for this run ({error})', file=sys.stderr)
        sys.exit(int(pytest.ExitCode.USAGE_ERROR))

    recorder = SuiteLoadRecorder()
    exit_code = pytest.main(pytest_args, plugins=[FinderFronter(), recorder])
    load_failure_exit = exit_code in (pytest.ExitCode.USAGE_ERROR, pytest.ExitCode.INTERRUPTED)
    if can_attribute_load_failures and recorder.suite_failed_to_load and load_failure_exit:
        exit_code = __COLLECTION_FAILED_EXIT_CODE__
    sys.exit(exit_code)


if __name__ == '__main__':
    # An exception that escapes main (a plugin that cannot register, a corrupt sources file, a hook that raises
    # after the tests ran) would end the interpreter with exit 1, the code for a failing test, and score the
    # mutant as caught although no test failed. Exit with pytest's internal-error code instead; SystemExit and
    # KeyboardInterrupt pass through.
    # pytest.fail and pytest.skip raise BaseException subclasses, so the guard catches BaseException. The
    # parent keeps only the first 2000 characters of stderr, so a one-line cause comes before the traceback.
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as error:
        cause = ''.join(traceback.format_exception_only(type(error), error)).strip()
        print(
            f'pytest-gremlins: the gremlin subprocess crashed outside a test, so pytest did not finish: {cause[:500]}',
            file=sys.stderr,
        )
        traceback.print_exc()
        sys.exit(__INTERNAL_ERROR_EXIT_CODE__)
"""
    return (
        script.replace('__COLLECTION_FAILED_EXIT_CODE__', str(GREMLIN_COLLECTION_FAILED_EXIT_CODE))
        .replace('__USAGE_ERROR_EXIT_CODE__', str(int(pytest.ExitCode.USAGE_ERROR)))
        .replace('__INTERNAL_ERROR_EXIT_CODE__', str(int(pytest.ExitCode.INTERNAL_ERROR)))
        .replace('__UNATTRIBUTABLE_MARKER__', UNATTRIBUTABLE_MARKER)
        .replace('__ORIGIN_FINDER_SOURCE__', inspect.getsource(origin_finder))
        .replace('__NODE_ID_ARGS_SOURCE__', inspect.getsource(node_id_args))
    )


def _get_lightweight_runner_script() -> str:
    """Return a lightweight test runner that avoids full pytest startup.

    Instead of running ``pytest.main()``, this script directly imports test
    modules and calls test functions.  When it was enabled it skipped ~900ms
    of pytest startup per subprocess, at the cost of not reproducing what
    pytest does around a test call.

    The runner handles class-based tests (``TestFoo::test_bar``) and
    function-based tests (``test_bar``), with ``-x`` semantics (stop on
    first failure).  Exit 0 = survived, exit 1 = zapped, and
    ``LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE`` = the runner could not run a test
    faithfully and abstains rather than fabricate a verdict.

    The runner is not written by ``_write_instrumented_sources`` while it is disabled
    (https://github.com/mikelane/pytest-gremlins/issues/538); the generator is kept as groundwork.

    Returns:
        The lightweight runner script source code.
    """
    script = '''#!/usr/bin/env python
"""Lightweight test runner for pytest-gremlins -- skips full pytest startup."""

import importlib.util
import inspect
import json
import os
import sys
import traceback
import unittest

__ORIGIN_FINDER_SOURCE__


def install_origin_finder():
    """Install the origin finder from sources.json."""
    sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE')
    if not sources_file:
        return

    with open(sources_file, encoding='utf-8') as f:
        instrumented_sources = json.load(f)

    install(instrumented_sources)


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


CANNOT_VERIFY_EXIT_CODE = __CANNOT_VERIFY_EXIT_CODE__
PASSED = 'passed'
CAUGHT = 'caught'
CANNOT_VERIFY = 'cannot_verify'
OUTCOME_MODULES = ('builtins', '_pytest.outcomes')
UNEXECUTED_OUTCOMES = ('Skipped', 'XFailed')


def cannot_verify(test_spec, reason):
    """Report why a test could not be judged without pytest, and abstain."""
    sys.stderr.write('pytest-gremlins lightweight runner cannot verify %s: %s\\n' % (test_spec, reason))
    return CANNOT_VERIFY


def is_unexecuted_outcome(exc):
    """Return True when a pytest skip/xfail was raised from inside the test body."""
    if isinstance(exc, unittest.SkipTest):
        return True
    return type(exc).__module__ in OUTCOME_MODULES and type(exc).__name__ in UNEXECUTED_OUTCOMES


def resolve_test_callable(module, parts):
    """Return (callable, None) or (None, reason) for the node ID parts after the file."""
    owner = module
    if len(parts) == 2:
        cls = getattr(module, parts[0], None)
        if cls is None:
            return None, 'class %s not found' % parts[0]
        try:
            owner = cls()
        except Exception as exc:
            return None, 'class %s could not be instantiated: %r' % (parts[0], exc)
    func = getattr(owner, parts[-1], None)
    if not callable(func):
        return None, 'test %s not found' % parts[-1]
    try:
        inspect.signature(func).bind()
    except TypeError:
        return None, 'test requires arguments (fixtures or parametrization)'
    except ValueError:
        pass
    return func, None


def run_test(test_spec, rootdir):
    """Run a single test from its node ID.

    Returns PASSED, CAUGHT (the test body raised), or CANNOT_VERIFY when the
    test cannot be run faithfully as a bare callable.
    """
    parts = test_spec.split('::')
    if len(parts) not in (2, 3):
        return cannot_verify(test_spec, 'unexpected node ID format')

    try:
        module = load_test_module(os.path.join(rootdir, parts[0]))
    except Exception as exc:
        return cannot_verify(test_spec, 'test module failed to load: %r' % (exc,))
    if module is None:
        return cannot_verify(test_spec, 'test module could not be imported')

    func, reason = resolve_test_callable(module, parts[1:])
    if func is None:
        return cannot_verify(test_spec, reason)

    try:
        returned = func()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        if is_unexecuted_outcome(exc):
            return cannot_verify(test_spec, 'test was skipped or xfailed at runtime')
        return CAUGHT

    if inspect.isawaitable(returned) or inspect.isgenerator(returned):
        if hasattr(returned, 'close'):
            returned.close()
        return cannot_verify(test_spec, 'test returned an awaitable or generator that pytest would drive')
    return PASSED


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
    install_origin_finder()

    unverifiable = False
    for spec in sys.argv[1:]:
        outcome = run_test(spec, rootdir)
        if outcome == CAUGHT:
            sys.exit(1)
        if outcome == CANNOT_VERIFY:
            unverifiable = True

    sys.exit(CANNOT_VERIFY_EXIT_CODE if unverifiable else 0)


def guarded_main():
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(CANNOT_VERIFY_EXIT_CODE)


if __name__ == '__main__':
    guarded_main()
'''
    return script.replace('__CANNOT_VERIFY_EXIT_CODE__', str(LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE)).replace(
        '__ORIGIN_FINDER_SOURCE__', inspect.getsource(origin_finder)
    )


def _cleanup_instrumented_dir(instrumented_dir: Path | None) -> None:
    """Clean up the temporary instrumented files directory.

    Args:
        instrumented_dir: Path to the directory to remove, or None.
    """
    if instrumented_dir is not None and instrumented_dir.exists():
        shutil.rmtree(instrumented_dir, ignore_errors=True)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
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

    if _skip_mutation_unless_baseline_is_green(gremlin_session, exitstatus):
        return

    config = session.config
    rootdir = _get_rootdir(config)

    if gremlin_session.xdist_active:
        _rebuild_state_from_xdist_workers(session, gremlin_session, rootdir)

    if not gremlin_session.gremlins:
        if gremlin_session.explain_gremlin_id is not None:
            _print_terminal_notices(gremlin_session)
            cause = (
                'Files were skipped (see above).'
                if gremlin_session.skipped_files
                else 'Check your `paths`/`--gremlin-targets` configuration.'
            )
            print(f'--gremlin-explain: no gremlins were generated in this session (nothing to explain). {cause}')
            gremlin_session.enabled = False
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

    if _maybe_short_circuit_for_explain(gremlin_session):
        return

    _verify_suite_loads_unmutated(session, gremlin_session)
    gremlin_session.results = _dispatch_mutation_run(session, gremlin_session)
    _report_unmapped_selections(gremlin_session)


def _verify_suite_loads_unmutated(session: pytest.Session, gremlin_session: GremlinSession) -> None:
    """Check that the gremlin subprocess can load the unmutated suite, before any gremlin runs.

    A load failure under a mutant is only attributable to the mutant if the same subprocess
    harness loads the suite cleanly without one. The baseline run is a different process, so it
    cannot vouch for that. When the control run fails, a marker next to ``sources.json`` makes the
    bootstrap stop reporting load failures as kills, so every mapping site scores them as errors.
    Only gremlins that will actually run count: pardoned, unrunnable and cached ones are skipped, and when none
    is left no subprocess is spawned and nothing is printed. The union of the remaining selections is
    an early-out only; each collection kill is confirmed against its own selection by
    :func:`_confirm_collection_kill`.
    """
    instrumented_dir = gremlin_session.instrumented_dir
    if instrumented_dir is None:
        return
    gremlins_to_run = 0
    selected_node_ids: set[str] = set()
    for gremlin in gremlin_session.gremlins:
        if _immediate_result_if_pardoned(gremlin) is not None:
            continue
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        if _immediate_result_if_selection_unrunnable(gremlin, gremlin_session) is not None:
            continue
        if _check_cache_for_gremlin(gremlin, selected_tests, gremlin_session) is not None:
            continue
        selected_node_ids.update(_node_ids_for_tests(selected_tests, gremlin_session))
        gremlins_to_run += 1
    if not gremlins_to_run:
        return
    outcome = _collect_unmutated(gremlin_session, _get_rootdir(session.config), sorted(selected_node_ids))
    logger.debug('Unmutated control run took %.1fs (loads cleanly: %s)', outcome.seconds, outcome.loads_cleanly)
    if outcome.loads_cleanly:
        return
    gremlin_session.load_failures_attributable = False
    try:
        (instrumented_dir / UNATTRIBUTABLE_MARKER).write_text('', encoding='utf-8')
    except OSError as write_error:
        print(
            f'pytest-gremlins: could not write the load-failure marker ({write_error}); '
            'load failures under a mutant may be scored as kills.',
            file=sys.stderr,
        )
    print(build_diagnostic(outcome.output), file=sys.stderr)


def _unmutated_command_and_env(gremlin_session: GremlinSession, rootdir: Path) -> tuple[list[str], dict[str, str]]:
    """Return a gremlin run's base command and environment, minus the gremlin."""
    instrumented_dir = gremlin_session.instrumented_dir
    command = _build_test_command(
        instrumented_dir,
        gremlin_session.preserved_addopts,
        xdist_loaded=gremlin_session.xdist_loaded,
        xdist_loader_options=gremlin_session.xdist_loader_options,
        doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
        rerun_options=gremlin_session.rerun_options,
        pytest_cov_options=gremlin_session.pytest_cov_options,
    )
    env = env_without_xdist_addopts(os.environ)
    env.pop(ACTIVE_GREMLIN_ENV_VAR, None)
    env['GREMLIN_ROOTDIR'] = str(rootdir)
    if instrumented_dir is not None:
        env[GREMLIN_SOURCES_ENV_VAR] = str(instrumented_dir / 'sources.json')
    export_spawn_hook(env)
    return command, env


def _collect_unmutated(
    gremlin_session: GremlinSession,
    rootdir: Path,
    node_ids: Sequence[str],
) -> ControlRunOutcome:
    """Collect ``node_ids`` with the bootstrap, using a gremlin run's command and env minus the gremlin."""
    command, env = _unmutated_command_and_env(gremlin_session, rootdir)
    return run_control(command, node_ids, rootdir, env, node_ids_dir=gremlin_session.instrumented_dir)


def _confirm_collection_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Keep a collection kill only if the unmutated run of the gremlin's own selection loads.

    The control run vouches for the union of all selected tests, but a gremlin collects only its
    own subset, and a subset can fail to load without its siblings (for example a module that
    needs ``sys.path`` changes made by another module). The check runs in the parent, where the
    result arrives, so the memo is shared by every execution mode and pool worker processes need
    no state of their own. It costs one collect-only run per distinct selection, and only for
    gremlins that were reported as collection kills.

    Args:
        result: The gremlin's result from the subprocess.
        node_ids: The node ids the gremlin's subprocess was asked to run, in command order.
        gremlin_session: The current gremlin session, holding the memo.
        rootdir: Root directory of the project.

    Returns:
        ``result`` unchanged, or an ERROR result when the unmutated selection fails to load.
    """
    if result.status != GremlinResultStatus.ZAPPED or result.killing_test != COLLECTION_KILLING_TEST:
        return result
    selection = tuple(node_ids)
    if selection not in gremlin_session.unmutated_load_checks:
        gremlin_session.unmutated_load_checks[selection] = _collect_unmutated(gremlin_session, rootdir, node_ids)
    outcome = gremlin_session.unmutated_load_checks[selection]
    if outcome.loads_cleanly:
        return result
    return dataclass_replace(
        result,
        status=GremlinResultStatus.ERROR,
        killing_test=None,
        error_output=f'{SELECTION_FAILS_TO_LOAD_PREFIX}\n{outcome.output[-MAX_SELECTION_FAILURE_OUTPUT_CHARS:]}',
    )


def _prefill_collection_kill_confirmations(
    pending: Sequence[tuple[GremlinResult, Sequence[str]]],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> None:
    """Fill the unmutated-load memo for every collection kill in ``pending``, running distinct selections concurrently.

    Collection confirmations measure no time, so they can overlap; timeout confirmations compare
    durations and must stay solo, so they are not touched here. Worker threads only run the
    subprocess; the memo is written from the calling thread, so it needs no lock. Concurrency is
    bounded by the configured worker count. :func:`_confirm_collection_kill` then reads the warm memo
    and decides each verdict exactly as before.

    Args:
        pending: Each result paired with the node ids its subprocess was asked to run.
        gremlin_session: The current gremlin session, holding the memo and the worker count.
        rootdir: Root directory of the project.
    """
    selections = {
        tuple(node_ids): node_ids
        for result, node_ids in pending
        if result.status == GremlinResultStatus.ZAPPED and result.killing_test == COLLECTION_KILLING_TEST
    }
    unchecked = [selection for selection in selections if selection not in gremlin_session.unmutated_load_checks]
    if not unchecked:
        return
    worker_count = min(len(unchecked), gremlin_session.parallel_workers or os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        outcomes = executor.map(
            lambda selection: _collect_unmutated(gremlin_session, rootdir, selections[selection]), unchecked
        )
        gremlin_session.unmutated_load_checks.update(zip(unchecked, outcomes, strict=True))


def _confirm_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Confirm a collection kill or a timeout against the gremlin's own unmutated selection."""
    result = _confirm_collection_kill(result, node_ids, gremlin_session, rootdir)
    return _confirm_timeout_kill(result, node_ids, gremlin_session, rootdir)


def _confirm_timeout_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Keep a timeout as a kill only if the gremlin's own selection finishes in time without a mutant.

    A gremlin times out when its tests outlast ``mutant_timeout``. If the same tests outlast it
    with no mutant at all, the timeout says nothing about the mutant, and counting it as a kill
    would score a suite that asserts nothing as perfect. Such a result becomes an ERROR, which stays
    in the score's denominator, so a timeout that is too short can only lower the score. Like
    :func:`_confirm_collection_kill`, the check runs in the parent where the result arrives, so it
    covers every execution mode, and it runs once per distinct selection.

    Args:
        result: The gremlin's result from the subprocess.
        node_ids: The node ids the gremlin's subprocess was asked to run, in command order.
        gremlin_session: The current gremlin session, holding the memo and the timeout.
        rootdir: Root directory of the project.

    Returns:
        ``result`` unchanged, or an ERROR result when the unmutated selection times out, takes more than
        ``TIMEOUT_CONFIRMATION_HEADROOM`` of the limit, or cannot be launched.
    """
    if result.status != GremlinResultStatus.TIMEOUT:
        return result
    selection = tuple(node_ids)
    if selection not in gremlin_session.unmutated_timeout_checks:
        command, env = _unmutated_command_and_env(gremlin_session, rootdir)
        gremlin_session.unmutated_timeout_checks[selection] = run_unmutated(
            command,
            node_ids,
            rootdir,
            env,
            timeout=gremlin_session.mutant_timeout,
            node_ids_dir=gremlin_session.instrumented_dir,
        )
        outcome = gremlin_session.unmutated_timeout_checks[selection]
        logger.debug(
            'Timeout confirmation: unmutated run of %d node ids took %.1fs (timed out: %s)',
            len(selection),
            outcome.seconds,
            outcome.timed_out,
        )
    unmutated_outcome = gremlin_session.unmutated_timeout_checks[selection]
    if unmutated_outcome.launch_error is not None:
        return dataclass_replace(
            result,
            status=GremlinResultStatus.ERROR,
            error_output=f'{TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX} {unmutated_outcome.launch_error}',
        )
    mutant_timeout = gremlin_session.mutant_timeout
    fits_in_headroom = unmutated_outcome.seconds <= mutant_timeout * TIMEOUT_CONFIRMATION_HEADROOM
    if not unmutated_outcome.timed_out and fits_in_headroom:
        return result
    return dataclass_replace(
        result,
        status=GremlinResultStatus.ERROR,
        error_output=_timeout_not_confirmed_message(
            selection, mutant_timeout, unmutated_outcome, gremlin_session.mutant_attempt_timeout
        ),
    )


def _timeout_not_confirmed_message(
    selection: Sequence[str],
    mutant_timeout: int,
    unmutated_outcome: UnmutatedRunOutcome,
    attempt_timeout: int | None = None,
) -> str:
    """Explain a downgraded timeout: the selection, how the unmutated run went, the limit, and how to raise it."""
    shown_ids = ', '.join(selection[:MAX_SELECTION_IDS_IN_MESSAGE]) or 'the whole suite'
    hidden_count = len(selection) - MAX_SELECTION_IDS_IN_MESSAGE
    if hidden_count > 0:
        shown_ids += f' (and {hidden_count} more)'
    headroom_percent = f'{TIMEOUT_CONFIRMATION_HEADROOM:.0%}'
    scaled_note = scaled_limit_note(attempt_timeout, mutant_timeout)
    unmutated_run_summary = (
        f'did not finish in {mutant_timeout}s{scaled_note}'
        if unmutated_outcome.timed_out
        else (
            f'took {unmutated_outcome.seconds:.1f}s, over {headroom_percent} of the {mutant_timeout}s limit'
            f'{scaled_note}'
        )
    )
    raised_limit = 'the per-attempt limit' if scaled_note else 'the limit'
    is_capped = bool(scaled_note) and limit_is_capped(mutant_timeout)
    advice = (
        f'{CAPPED_LIMIT_ADVICE[0].upper()}{CAPPED_LIMIT_ADVICE[1:]}'
        if is_capped
        else f'Raise {raised_limit} with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout'
    )
    return (
        f'{TIMEOUT_NOT_CONFIRMED_PREFIX} (selection: {shown_ids}; unmutated run {unmutated_run_summary}). '
        f'{advice}, or speed up these tests.'
    )


def _rerun_timeout_alone(
    result: GremlinResult,
    test_command: list[str],
    rootdir: Path,
    gremlin_session: GremlinSession,
) -> GremlinResult:
    """Re-run a pooled TIMEOUT by itself, so it competes with nothing the unmutated run does not.

    A gremlin that timed out among parallel workers or in a batch may only have been slowed by them
    (a shared lock, a saturated CPU), while the unmutated confirmation runs alone. Running the mutated
    gremlin alone under the same selection and timeout compares like with like; if it finishes, its
    verdict is scored as usual.

    Args:
        result: The pooled result.
        test_command: The command the pooled run used.
        rootdir: Root directory of the project.
        gremlin_session: The current gremlin session.

    Returns:
        ``result`` unchanged unless it is a TIMEOUT, otherwise the solo run's result.
    """
    if result.status != GremlinResultStatus.TIMEOUT:
        return result
    solo_result = _test_gremlin(
        result.gremlin,
        test_command,
        rootdir,
        gremlin_session.instrumented_dir,
        timeout=gremlin_session.mutant_timeout,
    )
    logger.debug('Pooled timeout of %s re-run alone: %s', result.gremlin.gremlin_id, solo_result.status.value)
    return dataclass_replace(solo_result, selected_tests=result.selected_tests)


def _confirm_pooled_result(
    result: GremlinResult,
    test_command: list[str],
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Judge a parallel or batch result: re-run a timeout alone, then apply the usual confirmations."""
    result = _rerun_timeout_alone(result, test_command, rootdir, gremlin_session)
    return _confirm_kill(result, node_ids, gremlin_session, rootdir)


def _node_ids_for_tests(selected_tests: Sequence[str], gremlin_session: GremlinSession) -> list[str]:
    """Return the node ids behind ``selected_tests``, in order, skipping names with no node id."""
    return [
        gremlin_session.test_node_ids[test_name]
        for test_name in selected_tests
        if test_name in gremlin_session.test_node_ids
    ]


def _rebuild_state_from_xdist_workers(
    session: pytest.Session,
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> None:
    """Reconstruct the item list from worker-reported IDs and generate gremlins (xdist Phase 2)."""
    xdist_ids = gremlin_session.xdist_item_ids or []
    if not xdist_ids:
        logger.warning(
            'pytest_sessionfinish: xdist Phase 2 starting with zero item IDs; '
            'pytest_xdist_node_collection_finished may not have fired'
        )
    normalized = _make_node_ids_relative(xdist_ids, rootdir)
    gremlin_session.test_node_ids = {nid: nid for nid in normalized}
    xdist_name_to_nodes: dict[str, list[str]] = {}
    for nid in normalized:
        func_name = nid.split('::')[-1]
        xdist_name_to_nodes.setdefault(func_name, []).append(nid)
    gremlin_session.test_name_to_node_ids = xdist_name_to_nodes
    gremlin_session.total_tests = len(normalized)
    logger.debug('pytest_sessionfinish: xdist Phase 2 reconstructed %d test node IDs', len(normalized))
    source_files = _discover_source_files(session, gremlin_session)
    gremlin_session.source_files = source_files
    _hash_sources_and_tests_for_cache(
        gremlin_session,
        source_files,
        rootdir,
        _test_file_patterns(gremlin_session, session.config),
        _pythonpath_entries(gremlin_session, session.config),
    )
    logger.debug('pytest_sessionfinish: xdist Phase 2 discovered %d source files', len(source_files))
    _generate_gremlins(gremlin_session, source_files, rootdir)
    logger.debug('pytest_sessionfinish: xdist Phase 2 generated %d gremlins', len(gremlin_session.gremlins))


_FIXED_BASELINE_SKIP_REASONS: dict[int, str] = {
    pytest.ExitCode.INTERRUPTED: 'the baseline test session was interrupted; rerun it to completion first',
    pytest.ExitCode.USAGE_ERROR: 'pytest reported a usage error (exit 4)',
    pytest.ExitCode.NO_TESTS_COLLECTED: 'no tests were collected',
}


_POSSIBLY_GREEN_STATUSES = (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED)

_NON_TEST_CHECK_NOTE = (
    'pytest-gremlins: baseline tests all passed; the non-zero exit came from a non-test check '
    '(e.g. --cov-fail-under), so mutation testing continues'
)


def _baseline_skip_reason(gremlin_session: GremlinSession, exitstatus: int) -> str:
    """Explain why a non-green baseline cannot back mutation verdicts."""
    if gremlin_session.collection_errors:
        return f'test collection failed ({gremlin_session.collection_errors} error(s)); fix the collection errors first'
    failed_tests = len(gremlin_session.baseline_failed_test_ids)
    if exitstatus == pytest.ExitCode.TESTS_FAILED and failed_tests:
        return f'{failed_tests} baseline test(s) failed; mutation scores need a passing suite'
    if gremlin_session.baseline_aborted and exitstatus in _POSSIBLY_GREEN_STATUSES:
        return 'the baseline test session was stopped early (pytest.exit)'
    return _FIXED_BASELINE_SKIP_REASONS.get(exitstatus, f'the baseline run ended with exit code {int(exitstatus)}')


def _is_green_baseline(gremlin_session: GremlinSession, exitstatus: int) -> bool:
    """Whether every baseline test ran to completion and passed.

    Exit status 1 with no failed test report means a non-test check (such as
    ``--cov-fail-under``) failed the run, which does not undermine the tests.
    """
    return (
        exitstatus in _POSSIBLY_GREEN_STATUSES
        and not gremlin_session.baseline_aborted
        and not gremlin_session.collection_errors
        and not gremlin_session.baseline_failed_test_ids
    )


def _skip_mutation_unless_baseline_is_green(gremlin_session: GremlinSession, exitstatus: int) -> bool:
    """Disable mutation testing unless the baseline is positively green.

    A gremlin is zapped when a covering test fails, so a baseline with failing
    tests, collection errors, or an aborted run would yield unfounded verdicts.
    This is an allowlist: only a completed run whose tests all passed proceeds
    (exit status OK, or TESTS_FAILED caused solely by a non-test check, which
    prints a note).  Anything else prints one reason to stderr and disables the
    session so no report is rendered.  pytest's own exit status is never changed.

    Returns:
        True when the caller must stop without running mutation testing.
    """
    if _is_green_baseline(gremlin_session, exitstatus):
        if exitstatus == pytest.ExitCode.TESTS_FAILED:
            print(_NON_TEST_CHECK_NOTE, file=sys.stderr)
        for ini_warning in gremlin_session.rerun_ini_warnings:
            print(ini_warning, file=sys.stderr)
        rerun_warning = baseline_rerun_warning(gremlin_session.baseline_rerun_test_ids)
        if rerun_warning is not None:
            print(rerun_warning, file=sys.stderr)
        return False
    reason = _baseline_skip_reason(gremlin_session, exitstatus)
    for notice in gremlin_session.terminal_notices:
        print(notice, file=sys.stderr)
    print(f'pytest-gremlins: skipping mutation testing because {reason}', file=sys.stderr)
    gremlin_session.enabled = False
    return True


def _print_terminal_notices(gremlin_session: GremlinSession) -> None:
    """Print the queued terminal notices for paths that disable the session before the summary hook."""
    for notice in gremlin_session.terminal_notices:
        print(notice)


def _maybe_short_circuit_for_explain(gremlin_session: GremlinSession) -> bool:
    """Run ``--gremlin-explain`` if requested and report whether to bail out.

    When ``explain_gremlin_id`` is set we print the diagnostic, disable the
    session, and tell the caller to skip the mutation loop. Returns ``True``
    when the caller must return without running mutations.
    """
    if gremlin_session.explain_gremlin_id is None:
        return False
    _emit_selection_explainer(gremlin_session)
    gremlin_session.results = []
    return True


def _dispatch_mutation_run(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Pick the execution mode (batch / parallel / default) and run it."""
    if gremlin_session.batch_enabled:
        return _run_batch_mutation_testing(session, gremlin_session)
    if gremlin_session.parallel_enabled:
        return _run_parallel_mutation_testing(session, gremlin_session)
    return _run_mutation_testing(session, gremlin_session)


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
        cleaned_node_id = strip_marker_suffix(node_id)

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


def _report_diagnostic(message: str) -> None:
    """Write a run-time diagnostic to stderr.

    Not ``warnings.warn``: these run inside ``pytest_sessionfinish``, where a user's
    ``filterwarnings = error`` would escalate them into a crash (issue #543).

    Args:
        message: The diagnostic text, written as a single line to stderr.
    """
    print(message, file=sys.stderr)


def _warn_prescan_timeout(seconds: int, attempt_timeout: int | None = None) -> None:
    """Warn that the pre-scan timed out, which is a different cause from "no data" (issues #503, #673)."""
    scaled_note = scaled_limit_note(attempt_timeout, seconds)
    raised_limit = 'the per-attempt limit' if scaled_note else 'it'
    advice = (
        CAPPED_LIMIT_ADVICE
        if scaled_note and limit_is_capped(seconds)
        else f'set coverage_timeout / --gremlin-coverage-timeout to raise {raised_limit}'
    )
    _report_diagnostic(
        f'pytest-gremlins: coverage pre-scan exceeded {seconds}s{scaled_note}; '
        'coverage-guided test selection disabled '
        f'({advice})'
    )


def _warn_prescan_launch_failure(launch_error: CoveragePrescanLaunchError) -> None:
    """Warn that the pre-scan could not be run, naming the cause (issue #485)."""
    _report_diagnostic(
        f'pytest-gremlins: coverage pre-scan could not start ({launch_error.cause}); '
        'coverage-guided test selection disabled, so every gremlin runs the full test suite'
    )


def _warn_no_coverage_data() -> None:
    """Warn that the pre-scan finished but recorded nothing (issue #113)."""
    _report_diagnostic(
        'Coverage collection returned no data. '
        'If you have --cov in pytest addopts, this may interfere with '
        "gremlins' coverage-guided test selection. "
        'See https://github.com/mikelane/pytest-gremlins/issues/113'
    )


def _run_prescan_reporting_problems(
    node_ids: list[str],
    rootdir: Path,
    gremlin_session: GremlinSession,
    *,
    coverage_include: list[str] | None,
) -> dict[str, dict[str, list[int]]]:
    """Run the coverage pre-scan, warning (with the right cause) when it yields nothing."""
    prescan_timeout = _prescan_timeout(gremlin_session)
    try:
        coverage_data = _run_tests_with_coverage(
            node_ids,
            rootdir,
            name_to_node_ids=gremlin_session.test_name_to_node_ids,
            coverage_include=coverage_include,
            preserved_addopts=gremlin_session.preserved_addopts,
            doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
            rerun_options=gremlin_session.rerun_options,
            timeout=prescan_timeout,
        )
    except CoveragePrescanTimeoutError as timeout_error:
        _warn_prescan_timeout(timeout_error.seconds, gremlin_session.coverage_attempt_timeout)
        return {}
    except CoveragePrescanLaunchError as launch_error:
        _warn_prescan_launch_failure(launch_error)
        return {}
    if not coverage_data:
        _warn_no_coverage_data()
    return coverage_data


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

    coverage_include = sorted({str(Path(gremlin.file_path).resolve()) for gremlin in gremlin_session.gremlins})

    coverage_data = _run_prescan_reporting_problems(
        relative_node_ids,
        rootdir,
        gremlin_session,
        coverage_include=coverage_include or None,
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


def _populate_coverage_from_line_bits(
    rows: list[tuple[int, int, bytes]],
    contexts: dict[int, str],
    files: dict[int, str],
    name_to_node_ids: dict[str, list[str]] | None,
    coverage_by_test: dict[str, dict[str, list[int]]],
) -> None:
    """Populate coverage_by_test from SQLite line_bits rows.

    Expands bare function names from coverage contexts to full node IDs
    using the reverse index, so downstream lookups (test selection, cache
    hashing) can match them against node-ID-keyed dicts.
    """
    for file_id, context_id, numbits in rows:
        if context_id not in contexts or file_id not in files:
            continue

        context = contexts[context_id]
        test_name = _extract_test_name_from_context(context)
        file_path = files[file_id]
        lines = _decode_numbits(numbits)

        if '::' not in test_name and name_to_node_ids:
            resolved_names = name_to_node_ids.get(test_name, [test_name])
        else:
            resolved_names = [test_name]

        for resolved_name in resolved_names:
            if resolved_name not in coverage_by_test:
                coverage_by_test[resolved_name] = {}
            if file_path not in coverage_by_test[resolved_name]:
                coverage_by_test[resolved_name][file_path] = []
            coverage_by_test[resolved_name][file_path].extend(lines)


# pytest-cov options that take NO value, so a token following them is unrelated and
# must be kept.  Every *other* cov option is treated as value-taking: when written
# without an inline ``=`` its following token is dropped as the value.  Erring toward
# "takes a value" keeps an unknown/new cov option (e.g. ``--cov-precision``) from
# leaving an orphaned value token behind; the explicit set below stops the known
# value-less switches from swallowing a following unrelated token.
_COV_FLAG_ONLY_OPTS = frozenset(
    {
        '--cov-branch',
        '--cov-append',
        '--cov-reset',
        '--no-cov',
        '--no-cov-on-fail',
    }
)

# ``--cov`` alone takes an *optional* value (pytest-cov defines it with
# ``nargs='?'``): a bare ``--cov`` immediately followed by another option has no
# value to consume, so the dash-prefix heuristic below only applies to this one
# option. Every other value-taking cov option (``--cov-report``,
# ``--cov-fail-under``, ``--cov-precision``, etc.) *requires* its value and must
# consume the next token unconditionally -- even one that happens to start with
# ``-`` (e.g. ``--cov-fail-under -1``) -- or it silently leaks into the
# re-injected addopts string as a stray, unrelated-looking token (issue #446).
_COV_OPTIONAL_VALUE_OPTS = frozenset({'--cov'})


def _is_cov_addopt(token: str) -> bool:
    """Return True if ``token`` is a pytest-cov option.

    Matches the exact ``--cov`` / ``--no-cov`` switches and their ``--cov-*`` /
    ``--no-cov-*`` families (each optionally with an inline ``=value``).  It does not
    match an unrelated option that merely shares the prefix, e.g.
    ``--covariance-threshold`` — pytest disables long-option abbreviation, so only the
    exact names and hyphenated families are pytest-cov's.
    """
    name = token.split('=', 1)[0]
    return name in ('--cov', '--no-cov') or name.startswith(('--cov-', '--no-cov-'))


# Registered as ``rerunfailures`` when found through its entry point (autoload, or ``-p rerunfailures``, which
# pytest resolves even with autoload disabled), as ``pytest_rerunfailures`` when loaded by module name
# (``-p pytest_rerunfailures``, ``pytest_plugins`` or ``PYTEST_PLUGINS``).
_RERUNFAILURES_ENTRY_POINT_NAME = 'rerunfailures'
_RERUNFAILURES_MODULE_NAME = 'pytest_rerunfailures'
_RERUNFAILURES_PLUGIN_NAMES = (_RERUNFAILURES_ENTRY_POINT_NAME, _RERUNFAILURES_MODULE_NAME)
# Blocking by the entry-point name also blocks the plugin when it is loaded by module name.
_BLOCK_RERUNFAILURES_OPTION = ('-p', 'no:rerunfailures')
_CONFTEST_FILE_NAME = 'conftest.py'  # pytest registers a conftest under its file path
_DISABLE_PLUGIN_AUTOLOAD_ENV_VAR = 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'
_DISABLE_PLUGIN_AUTOLOAD_FLAG = '--disable-plugin-autoload'


def _arguments_gremlin_runs_inherit(config: pytest.Config) -> list[str]:
    """Return the arguments gremlin runs get from the project's ``addopts`` and from ``PYTEST_ADDOPTS``.

    The session's own command line is not among them: gremlin runs are given neither its flags nor its ``-p``.
    ``@file`` arguments are expanded, as pytest does, against the directory gremlin runs start in, which is the
    rootdir (not the directory the session was started from).  One that cannot be read contributes nothing
    (pytest rejects an unreadable one as a usage error before this runs), which errs toward a missed loader and
    so toward a missed kill rather than a false one.
    """
    try:
        pytest_addopts_args = shlex.split(os.environ.get('PYTEST_ADDOPTS', ''))
    except ValueError:
        pytest_addopts_args = []
    return expand_argument_files([*config.getini('addopts'), *pytest_addopts_args], base_dir=_get_rootdir(config))


def _gremlin_runs_have_autoload_disabled(config: pytest.Config) -> bool:
    """Return whether gremlin runs start with pytest's plugin autoload disabled.

    They do when the environment they inherit sets the variable (pytest tests it for truthiness of the string),
    or when the flag reaches them through ``addopts`` or ``PYTEST_ADDOPTS``.  A flag typed on the session's command
    line does not reach them, so such a session's gremlin runs autoload their plugins.
    """
    return bool(os.environ.get(_DISABLE_PLUGIN_AUTOLOAD_ENV_VAR)) or (
        _DISABLE_PLUGIN_AUTOLOAD_FLAG in _arguments_gremlin_runs_inherit(config)
    )


def _plugin_names_loaded_by(tokens: Sequence[str]) -> set[str]:
    """Return the names ``-p <name>`` and ``-p<name>`` in ``tokens`` load (``-p no:<name>`` blocks)."""
    names = {value for flag, value in pairwise(tokens) if flag == '-p'}
    names |= {argument.removeprefix('-p') for argument in tokens if argument.startswith('-p') and argument != '-p'}
    return {name.strip() for name in names if not name.startswith('no:')}


def _command_line_loads_module(config: pytest.Config) -> bool:
    """Return whether the session's own command line names pytest-rerunfailures by module name."""
    arguments = expand_argument_files(list(config.invocation_params.args), base_dir=config.invocation_params.dir)
    return _RERUNFAILURES_MODULE_NAME in _plugin_names_loaded_by(arguments)


def _plugins_declared_by(module: object) -> set[str]:
    """Return the names a module lists in its ``pytest_plugins``, read the way pytest reads it.

    Pytest treats ``None`` (or any non-iterable) as empty and splits a string on commas.
    """
    declared = getattr(module, 'pytest_plugins', None)
    if isinstance(declared, str):
        return {name.strip() for name in declared.split(',')}
    if isinstance(declared, (list, tuple, set, frozenset)):
        return {name for name in declared if isinstance(name, str)}
    return set()


def _with_plugins_they_load(names: set[str]) -> set[str]:
    """Return ``names`` plus every plugin that those already imported modules load through ``pytest_plugins``."""
    pending = list(names)
    reached = set(names)
    while pending:
        for declared in _plugins_declared_by(sys.modules.get(pending.pop())):
            if declared not in reached:
                reached.add(declared)
                pending.append(declared)
    return reached


def _inherited_source_loads_module(config: pytest.Config) -> bool:
    """Return whether ``addopts``, ``PYTEST_ADDOPTS``, ``PYTEST_PLUGINS`` or a conftest loads the module by name.

    The load may be indirect: a plugin such as one of these names can itself list the module in its own
    ``pytest_plugins``.  Only conftests count: a plugin loaded on the command line is not inherited, whatever
    it declares.
    """
    names = _plugin_names_loaded_by(_arguments_gremlin_runs_inherit(config))
    names |= {name.strip() for name in os.environ.get('PYTEST_PLUGINS', '').split(',')}
    for name, plugin in config.pluginmanager.list_name_plugin():
        if name.endswith(_CONFTEST_FILE_NAME):
            names |= _plugins_declared_by(plugin)
    return _RERUNFAILURES_MODULE_NAME in _with_plugins_they_load(names)


def _gremlin_runs_would_load_the_module_twice(config: pytest.Config) -> bool:
    """Return whether gremlin runs would register pytest-rerunfailures under both of its names (issue #684).

    The session turned autoload off on its command line only, which gremlin runs never see, and loaded the
    plugin by module name through a source they inherit (conftest ``pytest_plugins``, ``PYTEST_PLUGINS`` or ini
    ``addopts``).  A gremlin run that autoloads would register the ``rerunfailures`` entry point and then load
    the module again as ``pytest_rerunfailures``, which pluggy rejects.  Blocking ``rerunfailures`` is no answer:
    pytest then blocks the module name too and nothing reruns.  When only the command line names the module,
    nothing is inherited that could load it twice, so gremlin runs keep autoload (and the other plugins the
    command line loaded) and reach the plugin through its entry point (issue #679 covers the rest).
    """
    return (
        bool(getattr(config.option, 'disable_plugin_autoload', False))
        and not _gremlin_runs_have_autoload_disabled(config)
        and config.pluginmanager.hasplugin(_RERUNFAILURES_MODULE_NAME)
        and not config.pluginmanager.hasplugin(_RERUNFAILURES_ENTRY_POINT_NAME)
        and (not _command_line_loads_module(config) or _inherited_source_loads_module(config))
    )


def _loader_options_for_gremlin_runs(config: pytest.Config, plugin_names: tuple[str, ...]) -> list[str]:
    """Return the ``-p`` option that makes gremlin runs load the plugin this session registered.

    Only for gremlin runs that start with autoload disabled (see :func:`_gremlin_runs_have_autoload_disabled`);
    with autoload on they load the plugin through its entry point, and a loader of another name would register
    the same module twice, which pluggy rejects.  The option repeats the name the session registered, so it is
    skipped when ``addopts``, ``PYTEST_ADDOPTS``, ``PYTEST_PLUGINS`` or a conftest loads the plugin as well:
    those reach the session too, which would have failed already had they used a different name.  The module
    is registered under exactly one of ``plugin_names``: as the entry-point name for ``-p <entry point>``, which
    pytest resolves even with autoload disabled, or as the module name for ``-p <module>``, ``pytest_plugins`` and
    ``PYTEST_PLUGINS``.  Other plugins (pytest-cov, issue #657) can share this helper with their own names.
    """
    if not _gremlin_runs_have_autoload_disabled(config):
        return []
    return _loader_options_for(config, plugin_names)


def _loader_options_for(config: pytest.Config, plugin_names: tuple[str, ...]) -> list[str]:
    """Return ``-p`` and the first of ``plugin_names`` that this session registered, or nothing."""
    registered_name = next((name for name in plugin_names if config.pluginmanager.hasplugin(name)), None)
    return [] if registered_name is None else ['-p', registered_name]


# The entry-point name (``-p pytest_cov``, autoload) or the module name (``-p pytest_cov.plugin``, ``pytest_plugins``).
# The module name goes first: bare ``pytest_cov`` can also be the hookless package that ``PYTEST_PLUGINS`` registers.
_PYTEST_COV_PLUGIN_NAMES: tuple[str, ...] = ('pytest_cov.plugin', 'pytest_cov')
_PYTEST_COV_ENTRY_POINT_NAMES: tuple[str, ...] = _PYTEST_COV_PLUGIN_NAMES[1:]
_PYTEST_COV_BLOCKS = frozenset({'no:pytest_cov', 'no:cov'})
_NO_COV_OPTION = '--no-cov'


def _gremlin_runs_inherit_a_pytest_cov_block(config: pytest.Config) -> bool:
    """Return whether ``addopts`` or ``PYTEST_ADDOPTS`` hold ``-p no:pytest_cov`` (or ``-p no:cov``, ``-pno:...``)."""
    tokens = _arguments_gremlin_runs_inherit(config)
    blocked = {value for flag, value in pairwise(tokens) if flag == '-p'}
    blocked |= {argument.removeprefix('-p') for argument in tokens if argument.startswith('-p')}
    return not _PYTEST_COV_BLOCKS.isdisjoint(name.strip() for name in blocked)


def _pytest_cov_options_for(config: pytest.Config, rerun_options: Sequence[str]) -> list[str]:
    """Return the pytest-cov options for gremlin runs: ``--no-cov``, and a loader when they need one (issue #654).

    ``--no-cov`` exists only where pytest-cov is registered, so it is forwarded only when this session has the option
    (``config.option.no_cov``), never merely because the package is importable.  Gremlin runs get a ``-p`` loader
    for the name this session registered it under, so the flag always has a plugin to parse it.  Repeating that name
    is a no-op where an inherited source loaded it as well, while a different name would register it twice.

    The loader matters in two setups:

    * Gremlin runs that start with autoload disabled (the environment, a flag in ``addopts`` or ``PYTEST_ADDOPTS``,
      or the ``--disable-plugin-autoload`` the rerun options forward, issue #684) do not register pytest-cov
      themselves.
    * Gremlin runs that autoload still do not when the inherited ``addopts`` or ``PYTEST_ADDOPTS`` hold
      ``-p no:pytest_cov`` and only the session's own command line (not passed on) loaded it again.  The later
      ``-p`` overrides the inherited block.

    With autoload on, only the entry-point name is forwarded, because the module name would register the autoloaded
    plugin a second time.  The exception is an inherited ``-p no:pytest_cov`` (or ``no:cov``): the gremlin run then
    does not autoload pytest-cov, so a session that registered only the module name gets that name forwarded too.  A
    block typed only on the session's command line is not inherited, so it changes nothing.

    If the session registered pytest-cov under a name this does not know, autoloading runs still get the bare flag,
    which they can parse where nothing blocks the plugin, and runs without autoload get nothing, which errs toward a
    missed kill.

    Args:
        config: The session's pytest config, read for the registered plugins, ``no_cov`` and the inherited
            ``addopts``.
        rerun_options: The options forwarded to gremlin runs by :func:`_rerun_options_for`, checked for
            ``--disable-plugin-autoload``.

    Returns:
        The options to append to every gremlin run command: ``[]``, ``['--no-cov']`` or
        ``['-p', <plugin name>, '--no-cov']``.
    """
    if not hasattr(config.option, 'no_cov'):
        return []
    if _gremlin_runs_have_autoload_disabled(config) or _DISABLE_PLUGIN_AUTOLOAD_FLAG in rerun_options:
        loader_options = _loader_options_for(config, _PYTEST_COV_PLUGIN_NAMES)
        return [*loader_options, _NO_COV_OPTION] if loader_options else []
    autoloaded_names = (
        _PYTEST_COV_PLUGIN_NAMES if _gremlin_runs_inherit_a_pytest_cov_block(config) else _PYTEST_COV_ENTRY_POINT_NAMES
    )
    return [*_loader_options_for(config, autoloaded_names), _NO_COV_OPTION]


_XDIST_PLUGIN_NAMES: tuple[str, ...] = ('xdist.plugin', 'xdist')
_XDIST_ENTRY_POINT_NAME = 'xdist'


_XDIST_BLOCKS = frozenset({'no:xdist', 'no:xdist.plugin'})


def _gremlin_runs_inherit_an_xdist_block(config: pytest.Config) -> bool:
    """Return whether ``addopts`` or ``PYTEST_ADDOPTS`` block xdist: ``-p no:xdist`` or ``-p no:xdist.plugin``.

    The attached spelling (``-pno:xdist``) counts too.
    """
    tokens = _arguments_gremlin_runs_inherit(config)
    blocked = {value for flag, value in pairwise(tokens) if flag == '-p'}
    blocked |= {argument.removeprefix('-p') for argument in tokens if argument.startswith('-p')}
    return not _XDIST_BLOCKS.isdisjoint(name.strip() for name in blocked)


def _xdist_options_for(config: pytest.Config, rerun_options: Sequence[str]) -> tuple[list[str], bool]:
    """Return the ``-p`` loader for gremlin runs and whether they get ``-n 0`` (issue #668).

    ``-n`` exists only where pytest-xdist is registered.  With autoload on, gremlin runs register it through its
    entry point, so ``-n 0`` goes out when the session registered ``xdist`` and no loader is added (a second name
    would register the module twice).  Gremlin runs that start with autoload disabled (see
    :func:`_gremlin_runs_have_autoload_disabled`, or the flag the rerun options forward) register nothing
    themselves, so they get ``-p`` and the name the session registered it under, and ``-n 0`` goes out only then.
    Gremlin runs that autoload still do not register xdist when the inherited ``addopts`` or ``PYTEST_ADDOPTS``
    hold ``-p no:xdist`` (see :func:`_gremlin_runs_inherit_an_xdist_block`) and only the session's own command
    line, which is not passed on, loaded it again (issue #685).  They get the same loader as runs without
    autoload, and the later ``-p`` overrides the inherited block.  A block that hides xdist from the session too
    leaves nothing registered, so nothing is forwarded.
    A session whose xdist is registered under an unknown name gets neither, which errs toward a missed kill.

    Args:
        config: The session's pytest config, read for the registered plugins and the inherited ``addopts``.
        rerun_options: The options forwarded to gremlin runs by :func:`_rerun_options_for`, checked for
            ``--disable-plugin-autoload``.

    Returns:
        The loader options and whether to forward ``-n 0``.
    """
    gremlin_runs_skip_xdist = (
        _gremlin_runs_have_autoload_disabled(config)
        or _DISABLE_PLUGIN_AUTOLOAD_FLAG in rerun_options
        or _gremlin_runs_inherit_an_xdist_block(config)
    )
    if gremlin_runs_skip_xdist:
        loader_options = _loader_options_for(config, _XDIST_PLUGIN_NAMES)
        return loader_options, bool(loader_options)
    return [], config.pluginmanager.hasplugin(_XDIST_ENTRY_POINT_NAME)


def _rerun_ini_settings_are_forwarded(config: pytest.Config) -> bool:
    """Return whether the rerun ini settings are passed to gremlin runs: only when a ``-c`` file holds them.

    Without ``-c``/``--config-file`` a gremlin run finds the same project config file as this session, so it
    reads the settings itself and nothing is lost.  ``config.option.inifilename`` is the value of ``-c``
    wherever it came from (command line, ``PYTEST_ADDOPTS`` or an ``@file``), because pytest parses them all
    into one namespace.
    """
    return bool(getattr(config.option, 'inifilename', None))


_DOCTEST_FLAG = '--doctest-modules'
_DOCTEST_GLOB = '--doctest-glob'


def _doctest_options_in(args: Sequence[str]) -> list[str]:
    """Return the doctest collection options in ``args``, which decide whether a doctest node id exists (#594)."""
    options: list[str] = []
    tokens = iter(args)
    for token in tokens:
        if token == _DOCTEST_FLAG or token.startswith(f'{_DOCTEST_GLOB}='):
            options.append(token)
        elif token == _DOCTEST_GLOB:
            glob = next(tokens, None)
            if glob is not None:
                options.extend([token, glob])
    return options


def _doctest_ini_overrides(config: pytest.Config) -> list[str]:
    """Return ``-o`` argument pairs carrying the session's resolved doctest ini values (#594).

    They go on the gremlin command line as top-level arguments, never inside the ``-o addopts=<...>`` value:
    before pytest 9.1 a ``-o`` nested in an addopts value set by ``-o`` is ignored (#719).

    Gremlin runs re-read the project config, so a value set by ``-o`` or ``-c`` would be lost and a doctest that
    needs it (``NORMALIZE_WHITESPACE``) would fail in every run, fabricating a kill for every gremlin it covers.
    Resolving through ``getini`` covers ``-o``, ``-c`` and the project file alike.  The resolved value is always
    forwarded, even an empty one, because a bare gremlin run would otherwise fall back to pytest's default
    (``ELLIPSIS``).  The same values key the cache, since they decide whether a doctest passes.
    """
    overrides: list[str] = []
    for key in ('doctest_optionflags', 'doctest_encoding'):
        try:
            value = config.getini(key)
        except ValueError:
            continue
        text = ' '.join(value) if isinstance(value, list) else str(value)
        overrides.extend(['-o', f'{key}={text}'])
    return overrides


def _addopts_for_gremlin_runs(config: pytest.Config) -> str:
    """Return the ``addopts`` for gremlin runs: the project's, minus pytest-cov, plus the session's doctest options.

    A doctest node id such as ``sample.py::sample.classify`` only resolves where doctests are collected, and
    ``--doctest-modules`` typed on the command line is otherwise lost, because gremlin runs replace ``addopts``.
    The doctest ini values are not here: they travel as top-level ``-o`` arguments (see :func:`_doctest_ini_overrides`).
    Options inside an ``@argfile`` are not expanded.
    """
    project_addopts = _addopts_without_cov(config.getini('addopts'))
    doctest_options = ' '.join(shlex.quote(option) for option in _doctest_options_in(config.invocation_params.args))
    return ' '.join(part for part in (project_addopts, doctest_options) if part)


def _command_line_rerun_options(config: pytest.Config) -> list[str]:
    """Return the rerun options in the session's invocation arguments, ``@file`` arguments expanded."""
    return rerun_options_in(config.invocation_params.args, base_dir=config.invocation_params.dir)


def _rerun_options_for(config: pytest.Config) -> list[str]:
    """Return the rerun settings of ``config`` for gremlin runs, or none if pytest-rerunfailures is not active.

    That is the rerun options typed on the command line, preceded, only when the session was started with
    ``-c``/``--config-file`` (which gremlin runs are not given, so they do not read that file), by the rerun
    ini settings the main session resolved; the command line wins over them.  Without ``-c`` the gremlin
    runs read the project config themselves, and forwarding its values through ``--override-ini`` would only
    risk pytest altering them (issue #658).  Under ``-c`` a gremlin run finds the project's own config file
    instead, so every rerun key the ``-c`` file leaves unset, or whose items ``--override-ini`` would change,
    is reset to empty (the baseline's defaults) rather than left to that file; see
    :func:`_rerun_ini_warnings_for`.  A key whose parsed option is set, from the command line, ``addopts`` or
    ``PYTEST_ADDOPTS``, is neither forwarded nor reset: gremlin runs get those options themselves, and
    pytest-rerunfailures reads an option before its ini key.
    Settings are only forwarded when the plugin is loaded in this session, so a project without it
    never receives a flag its gremlin runs would reject as unrecognized (exit code 4).
    A session without the plugin loaded forwards a block (``-p no:rerunfailures``), so gremlin runs, which do not
    get the session's own ``-p no:rerunfailures`` or ``--disable-plugin-autoload``, do not autoload it and rerun
    with ini settings the session's budget never assumed (issue #670).  Blocking a plugin that is not installed
    is harmless.  A plugin that is loaded wins: ``-p no:pytest_rerunfailures`` blocks only the module name, the
    entry-point plugin loads anyway, and the session's budget assumes reruns.
    A session that loaded the plugin forwards a loader (``-p`` and the name it registered) first when gremlin
    runs start with autoload disabled, by the environment or by a flag in ``addopts`` or ``PYTEST_ADDOPTS``
    (see :func:`_loader_options_for_gremlin_runs`): without it they would not load a plugin the session got from its
    command line, and would not rerun while the budget assumes they do (issue #679).
    When the session disabled autoload on its command line only and registered the plugin under its module name,
    gremlin runs get ``--disable-plugin-autoload`` and the module loader instead, so an inherited module-name
    load registers it once (issue #684).
    """
    if not _rerunfailures_is_loaded(config):
        return list(_BLOCK_RERUNFAILURES_OPTION)
    loader_options = _loader_options_for_gremlin_runs(config, _RERUNFAILURES_PLUGIN_NAMES)
    if _gremlin_runs_would_load_the_module_twice(config):
        loader_options = [_DISABLE_PLUGIN_AUTOLOAD_FLAG, '-p', _RERUNFAILURES_MODULE_NAME]
    return [*loader_options, *_rerun_settings_for(config)]


def _rerun_settings_for(config: pytest.Config) -> list[str]:
    """Return the rerun options and ini settings of a session that loaded pytest-rerunfailures."""
    command_line_options = _command_line_rerun_options(config)
    if not _rerun_ini_settings_are_forwarded(config):
        return command_line_options
    ini_resolution = _rerun_ini_resolution_for(config)
    return [*ini_resolution.overrides, *ini_resolution.resets, *command_line_options]


def _rerun_ini_resolution_for(config: pytest.Config) -> RerunIniResolution:
    """Return the rerun ini overrides, resets and unforwardable keys gremlin runs get under ``-c``."""
    return resolve_rerun_ini(
        config.getini,
        overridden_by=_command_line_rerun_options(config),
        option_keys_set=rerun_keys_set_in(config.option),
    )


def _gremlin_run_rerun_budget(config: pytest.Config) -> RerunBudget:
    """Return the ``(reruns, reruns_delay)`` gremlin runs may use, or no reruns without pytest-rerunfailures.

    The incremental cache keys verdicts on it (issue #671): the scaled timeout alone cannot tell
    ``--gremlin-mutant-timeout 60`` from ``--gremlin-mutant-timeout 30 --reruns 1``.
    """
    if not _rerunfailures_is_loaded(config):
        return NO_RERUNS
    return session_rerun_budget(config.option, config.getini)


def _gremlin_run_rerun_backoff_factor(config: pytest.Config) -> float:
    """Return the delay backoff factor gremlin runs may use, or 1.0 without pytest-rerunfailures."""
    if not _rerunfailures_is_loaded(config):
        return 1.0
    return session_rerun_backoff_factor(config.option, config.getini)


def _gremlin_run_rerun_cache_settings(config: pytest.Config) -> str:
    """Return the settings beyond rerun count and delay that the cache keys verdicts on.

    Rerun settings count only with pytest-rerunfailures loaded: otherwise nothing reruns, and a stale ``only_rerun``
    ini key must not split the cache (#677).  The doctest ini settings are always part of it (#594).
    """
    doctest_settings = ' '.join(shlex.quote(token) for token in _doctest_ini_overrides(config))
    if not _rerunfailures_is_loaded(config):
        return doctest_settings
    read_ini: Callable[[str], object] = config.getini
    if _rerun_ini_settings_are_forwarded(config):
        read_ini = rerun_ini_as_gremlin_runs_read(read_ini, _rerun_ini_resolution_for(config).resets)
    return f'{rerun_cache_settings(config.option, read_ini)} {doctest_settings}'.strip()


def _prescan_timeout(gremlin_session: GremlinSession) -> int:
    """Return the pre-scan limit, paying the rerun delay once for each test the baseline had to rerun (issue #673).

    The pre-scan runs the whole suite, so every flaky test waits out the delays, not just one.  The baseline
    already ran the suite, so its rerun count is the best estimate there is; a timeout here only turns
    coverage-guided selection off.
    """
    attempt_timeout = gremlin_session.coverage_attempt_timeout
    if attempt_timeout is None:
        return gremlin_session.coverage_timeout
    reruns, reruns_delay = gremlin_session.rerun_budget
    return scaled_mutant_timeout(
        attempt_timeout,
        reruns=reruns,
        reruns_delay=reruns_delay,
        reruns_delay_backoff_factor=gremlin_session.rerun_backoff_factor,
        delayed_tests=len(gremlin_session.baseline_rerun_test_ids),
    )


def _rerun_scaled_timeout(config: pytest.Config, per_run_timeout: int, *, label: str) -> int:
    """Return ``per_run_timeout`` widened to the rerun budget of the session (issues #655, #672, #673).

    The mutant runs and the coverage pre-scan both inherit the session's pytest-rerunfailures settings, so a
    killed mutant's test (or a flaky test in the pre-scan) is rerun and, with ``--reruns-delay`` (scaled by
    ``--reruns-delay-backoff-factor``), waits between attempts.
    Without scaling, that alone would outlast the timeout and the kill would be reported as a timeout or
    error.  The configured timeout is the budget of one attempt; see
    :func:`~pytest_gremlins.rerun_options.scaled_mutant_timeout`.  Nothing is scaled when
    pytest-rerunfailures is not loaded.
    """
    if not _rerunfailures_is_loaded(config):
        return per_run_timeout
    reruns, reruns_delay = session_rerun_budget(config.option, config.getini)
    backoff_factor = session_rerun_backoff_factor(config.option, config.getini)
    scaled_timeout = scaled_mutant_timeout(
        per_run_timeout, reruns=reruns, reruns_delay=reruns_delay, reruns_delay_backoff_factor=backoff_factor
    )
    logger.debug(
        '%s timeout scaled for pytest-rerunfailures: %ds per attempt, reruns=%d, reruns_delay=%.1fs, '
        'backoff_factor=%s -> %ds',
        label,
        per_run_timeout,
        reruns,
        reruns_delay,
        backoff_factor,
        scaled_timeout,
    )
    return scaled_timeout


def _rerun_ini_warnings_for(config: pytest.Config) -> list[str]:
    """Return one warning per rerun ini setting that ``-c`` holds and gremlin runs cannot be given."""
    if not _rerunfailures_is_loaded(config) or not _rerun_ini_settings_are_forwarded(config):
        return []
    return [unforwarded_rerun_key_warning(key) for key in _rerun_ini_resolution_for(config).unforwardable_keys]


def _rerunfailures_is_loaded(config: pytest.Config) -> bool:
    """Return whether pytest-rerunfailures is registered in this session under either of its plugin names."""
    return any(config.pluginmanager.hasplugin(name) for name in _RERUNFAILURES_PLUGIN_NAMES)


def _addopts_without_cov(raw_addopts: list[str]) -> str:
    """Return the project's pytest ``addopts`` with pytest-cov options removed.

    gremlins must neutralize pytest-cov in the subprocess runs it spawns: ``--cov``
    hijacks the coverage pre-scan and corrupts mutation detection (issue #113). The
    original remedy, ``-o addopts=``, cleared *every* addopt, so options the project
    relies on for test collection — most notably ``--import-mode=importlib`` — were
    silently dropped too, disabling coverage-guided selection (issue #424).

    Only the ``--cov*`` / ``--no-cov*`` option family is stripped. A cov option written
    with a space-separated value (``--cov-report term``, ``--cov-precision 2``) has its
    value token dropped as well: required-value options (everything except ``--cov``
    itself and the known value-less switches in ``_COV_FLAG_ONLY_OPTS``) consume their
    following token unconditionally, even one that starts with ``-``
    (``--cov-fail-under -1``); ``--cov``'s optional value is only dropped when the
    following token doesn't itself look like an option. Inline forms
    (``--cov-report=term``) are self-contained. The result is a single string suitable
    for ``-o addopts=<...>``.

    Two rare cases are left as-is (both were also dropped by the previous blanket
    ``-o addopts=``, so this is strictly an improvement on the common case): a ``--cov``
    smuggled inside a pytest ``@argfile`` response token is not introspected, and bare
    positional addopts are preserved verbatim (they may broaden the inner collection).
    """
    kept: list[str] = []
    index = 0
    count = len(raw_addopts)
    while index < count:
        token = raw_addopts[index]
        index += 1
        if _is_cov_addopt(token):
            has_no_inline_value = '=' not in token
            is_value_taking = token not in _COV_FLAG_ONLY_OPTS
            has_next_token = index < count
            if has_no_inline_value and is_value_taking and has_next_token:
                next_looks_like_option = raw_addopts[index].startswith('-')
                if token not in _COV_OPTIONAL_VALUE_OPTS or not next_looks_like_option:
                    index += 1
            continue
        kept.append(token)
    return ' '.join(shlex.quote(token) for token in kept)


# A non-editable install imports pytest_gremlins before pytest can mark it for assertion rewriting, and pytest 9.2
# applies ini ``filterwarnings = error`` to that config-time warning. ``-W`` on the command line escapes the message
# and matches it at the start, so this ignores only the warning for this module and nothing for the user's modules.
ASSERT_REWRITE_WARNING_FILTER = (
    'ignore:Module already imported so cannot be rewritten; pytest_gremlins:pytest.PytestAssertRewriteWarning'
)

# sysmon (the default core on Python 3.14+) silently drops contexts set through
# Coverage.switch_context, crediting each line only to the first test that ran it.
# ctrace supports them; the rc route degrades to pytrace if CTracer is unavailable.
_COVERAGE_CORE_RC_LINE = 'core = ctrace'
_PRESCAN_OVERRIDING_ENV_VARS = frozenset({'COVERAGE_CORE', 'COVERAGE_FILE'})


def _prescan_env() -> dict[str, str]:
    """Return the environment for the pre-scan subprocess.

    ``COVERAGE_CORE`` overrides the rc file (a user-set sysmon would drop contexts) and
    ``COVERAGE_FILE`` redirects the data file away from ``rootdir/.coverage``, which is read
    afterwards, so both are removed.  pytest appends ``PYTEST_ADDOPTS`` to every invocation,
    so ``-n 2`` there would distribute the pre-scan just like ``-n 2`` in ``addopts``
    (issue #502), and a gremlins option there is unrecognized under ``-p no:gremlins``.
    Both are stripped from it, as are ``--cov*`` options, which would make pytest-cov fight the pre-scan's
    own collection (issue #669).  The variable is dropped if empty.
    """
    return env_with_stripped_addopts(
        {key: value for key, value in os.environ.items() if key not in _PRESCAN_OVERRIDING_ENV_VARS},
        lambda addopts: _addopts_without_cov(shlex.split(addopts_without_gremlins(addopts_without_xdist(addopts)))),
    )


def _launch_prescan(command: list[str], node_ids: list[str], rootdir: Path, timeout: int) -> None:
    """Run the pre-scan ``command`` on ``node_ids``, handed over in a file so the command line stays short (#485).

    Windows refuses a command line over 32,767 characters, which a large suite's node ids alone can exceed.
    The file lives in a temporary directory that is removed when the pre-scan ends, however it ends.

    Raises:
        CoveragePrescanTimeoutError: If the pre-scan exceeds ``timeout`` seconds.
        CoveragePrescanLaunchError: If the operating system cannot start the pre-scan.
    """
    try:
        with tempfile.TemporaryDirectory(prefix='pytest_gremlins_prescan_', ignore_cleanup_errors=True) as node_ids_dir:
            subprocess.run(  # Intentional: runs pytest test commands
                command_with_node_ids_file(command, node_ids, Path(node_ids_dir)),
                cwd=str(rootdir),
                capture_output=True,
                timeout=timeout,
                check=False,
                env=_prescan_env(),
            )
    except subprocess.TimeoutExpired as expired:
        raise CoveragePrescanTimeoutError(timeout) from expired
    except OSError as launch_error:
        raise CoveragePrescanLaunchError(launch_error) from launch_error


def _run_tests_with_coverage(
    test_node_ids: list[str],
    rootdir: Path,
    *,
    name_to_node_ids: dict[str, list[str]] | None = None,
    coverage_include: list[str] | None = None,
    preserved_addopts: str = '',
    doctest_ini_overrides: Sequence[str] = (),
    rerun_options: Sequence[str] = (),
    timeout: int = DEFAULT_COVERAGE_TIMEOUT_SECONDS,
) -> dict[str, dict[str, list[int]]]:
    """Run all tests with coverage collection using dynamic contexts.

    Uses coverage.py's dynamic_context feature to track which lines are
    covered by which test. This is much faster than running each test
    separately.

    Args:
        test_node_ids: List of pytest node IDs to run.
        rootdir: Root directory of the project.
        name_to_node_ids: Reverse index mapping bare function names to full
            node IDs.  When coverage.py records a bare name (old-format
            ``dynamic_context=test_function``), the map is used to expand it
            to every matching full node ID so downstream lookups succeed.
        coverage_include: Optional list of file paths to scope coverage
            tracing to.  When non-empty and contains no glob-special characters
            (``*?[]``), the generated coveragerc uses an ``include =`` list of
            these paths instead of ``source = .``, so coverage.py only traces
            the gremlin source files rather than the entire tree. If any path
            contains a glob-special character, falls back to ``source = .``
            (since coverage.py interprets ``include`` entries as fnmatch globs).
            Downstream post-processing discards non-gremlin coverage, so narrowing
            scope avoids wasted tracing and SQLite I/O without changing the result.
        preserved_addopts: The project's ``addopts`` with pytest-cov flags stripped
            (see :func:`_addopts_without_cov`), passed through as ``-o addopts=<...>``
            so collection-affecting options such as ``--import-mode=importlib`` survive
            into the subprocess. Defaults to ``''`` (clear all addopts). pytest-xdist
            options (``-n``, ``--dist``, ...) are stripped by
            :func:`~pytest_gremlins.xdist_options.addopts_without_xdist` (as is ``PYTEST_ADDOPTS``, see
            :func:`_prescan_env`), because coverage.py does not trace xdist workers
            and the pre-scan would otherwise record nothing (issue #502).  The xdist
            plugin itself stays loaded: without ``-n`` it runs in-process, so its
            fixtures and hooks still work.
        doctest_ini_overrides: The session's resolved doctest ini values as ``-o key=value`` argument pairs
            (see :func:`_doctest_ini_overrides`), kept outside ``addopts`` because pytest before 9.1 ignores a
            ``-o`` nested in an ``addopts`` value (issue #719).
        rerun_options: pytest-rerunfailures options from the command line (see
            :func:`~pytest_gremlins.rerun_options.rerun_options_in`), appended so a test that flakes
            before reaching the code under test is rerun, as in the baseline, and still lands in the
            coverage map.
        timeout: Seconds the pre-scan subprocess may run (default 120).

    Returns:
        Dict mapping test names to their coverage data (file path -> lines).

    Raises:
        CoveragePrescanTimeoutError: If the pre-scan exceeds ``timeout`` seconds.
        CoveragePrescanLaunchError: If the operating system cannot start the pre-scan.
    """
    coverage_db_path = rootdir / '.coverage'
    coverage_db_path.unlink(missing_ok=True)

    coveragerc_path = rootdir / '.coveragerc.gremlins'
    # coverage.py's include directive interprets paths as glob patterns.
    # Paths with literal glob-special characters (*?[]) cannot be safely
    # escaped for coverage.py's tokenizer. When any glob-special char is
    # present, fall back to source = . and rely on post-processing filtering
    # (lines ~1698-1716) to discard non-gremlin coverage.
    has_glob_special_chars = any(ch in p for p in (coverage_include or []) for ch in '*?[]')
    if coverage_include and not has_glob_special_chars:
        include_lines = '\n'.join(f'    {path}' for path in coverage_include)
        coveragerc_content = f'[run]\n{_COVERAGE_CORE_RC_LINE}\ninclude =\n{include_lines}\n'
    else:
        coveragerc_content = f'[run]\n{_COVERAGE_CORE_RC_LINE}\nsource = .\n'
    coveragerc_path.write_text(coveragerc_content, encoding='utf-8')

    cmd = [
        sys.executable,
        '-m',
        'coverage',
        'run',
        f'--rcfile={coveragerc_path}',
        '-m',
        'pytest_gremlins.coverage.prescan_main',
        '-p',
        'pytest_gremlins.coverage.subprocess_bootstrap',
        '-p',
        'no:gremlins',
        '-W',
        ASSERT_REWRITE_WARNING_FILTER,
        '-o',
        f'addopts={addopts_without_gremlins(addopts_without_xdist(preserved_addopts))}',
        *doctest_ini_overrides,
        '--tb=no',
        '-q',
        *rerun_options,
    ]

    try:
        _launch_prescan(cmd, test_node_ids, rootdir, timeout)
    except (CoveragePrescanTimeoutError, CoveragePrescanLaunchError):
        coveragerc_path.unlink(missing_ok=True)
        raise

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
        _populate_coverage_from_line_bits(
            cursor.fetchall(),
            contexts,
            files,
            name_to_node_ids,
            coverage_by_test,
        )

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


def _run_batch_mutation_testing(  # pragma: no cover
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing by grouping gremlins into batches handed to workers.

    Batching groups gremlins into worker tasks. It does not reduce subprocesses:
    each gremlin in a batch still gets its own bootstrap subprocess.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        List of results for each gremlin.
    """
    rootdir = _get_rootdir(session.config)
    base_test_command = _build_test_command(
        gremlin_session.instrumented_dir,
        gremlin_session.preserved_addopts,
        xdist_loaded=gremlin_session.xdist_loaded,
        xdist_loader_options=gremlin_session.xdist_loader_options,
        doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
        rerun_options=gremlin_session.rerun_options,
        pytest_cov_options=gremlin_session.pytest_cov_options,
    )
    gremlins = gremlin_session.gremlins

    # Build gremlin -> test mapping for filtering (prioritized order)
    gremlin_tests: dict[str, list[str]] = {}
    for gremlin in gremlins:
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        gremlin_tests[gremlin.gremlin_id] = selected_tests

    cached_results, uncached_gremlins = _split_gremlins_needing_a_run(gremlins, gremlin_tests, gremlin_session)

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

    try:
        test_command = _build_filtered_test_command(
            base_test_command,
            all_covering_tests,
            gremlin_session,
        )
    except OSError as write_error:
        logger.warning('Cannot launch the gremlin batch: %s', write_error)
        return cached_results + [
            GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ERROR,
                error_output=_node_ids_write_failure_output(write_error),
                selected_tests=gremlin_tests[gremlin.gremlin_id],
            )
            for gremlin in uncached_gremlins
        ]

    # Execute batches
    executor = BatchExecutor(
        batch_size=batch_size,
        max_workers=gremlin_session.parallel_workers,
        timeout=gremlin_session.mutant_timeout,
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

    batch_node_ids = _node_ids_for_tests(all_covering_tests, gremlin_session)
    unconfirmed: list[GremlinResult] = []
    for worker_result in worker_results:
        gremlin_id = worker_result.gremlin_id
        if gremlin_id not in gremlin_by_id:
            continue

        unconfirmed.append(
            GremlinResult(
                gremlin=gremlin_by_id[gremlin_id],
                status=worker_result.status,
                killing_test=worker_result.killing_test,
                execution_time_ms=worker_result.execution_time_ms,
                error_output=worker_result.error_output,
                selected_tests=gremlin_tests[gremlin_id],
            )
        )

    # Batch runs every gremlin with the one unified command, so that is the selection to confirm.
    _prefill_collection_kill_confirmations([(r, batch_node_ids) for r in unconfirmed], gremlin_session, rootdir)
    for unconfirmed_result in unconfirmed:
        gremlin_result = _confirm_pooled_result(
            unconfirmed_result, test_command, batch_node_ids, gremlin_session, rootdir
        )
        results.append(gremlin_result)
        _cache_gremlin_result(
            unconfirmed_result.gremlin, unconfirmed_result.selected_tests, gremlin_result, gremlin_session
        )

    return results


def _run_parallel_mutation_testing(  # pragma: no cover
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
    base_test_command = _build_test_command(
        gremlin_session.instrumented_dir,
        gremlin_session.preserved_addopts,
        xdist_loaded=gremlin_session.xdist_loaded,
        xdist_loader_options=gremlin_session.xdist_loader_options,
        doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
        rerun_options=gremlin_session.rerun_options,
        pytest_cov_options=gremlin_session.pytest_cov_options,
    )
    gremlins = gremlin_session.gremlins

    # Build gremlin -> test mapping for filtering (prioritized order)
    gremlin_tests: dict[str, list[str]] = {}
    for gremlin in gremlins:
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        gremlin_tests[gremlin.gremlin_id] = selected_tests

    cached_results, uncached_gremlins = _split_gremlins_needing_a_run(gremlins, gremlin_tests, gremlin_session)

    if not uncached_gremlins:
        return cached_results

    # Run uncached gremlins in parallel
    aggregator = ResultAggregator(total_gremlins=len(uncached_gremlins))

    # Prepare instrumented dir path for env var
    instrumented_dir_str = str(gremlin_session.instrumented_dir) if gremlin_session.instrumented_dir else None

    # Map gremlin_id -> Gremlin for result reconstruction
    gremlin_by_id = {g.gremlin_id: g for g in uncached_gremlins}

    print(f'\npytest-gremlins: Starting parallel execution with {gremlin_session.parallel_workers or "auto"} workers')

    test_commands: dict[str, list[str]] = {}
    launch_failed_ids: set[str] = set()
    with WorkerPool(
        max_workers=gremlin_session.parallel_workers,
        timeout=gremlin_session.mutant_timeout,
    ) as pool:
        # Submit all gremlins
        futures = {}
        for gremlin in uncached_gremlins:
            selected_tests = gremlin_tests[gremlin.gremlin_id]

            try:
                test_command = _build_filtered_test_command(
                    base_test_command,
                    selected_tests,
                    gremlin_session,
                )
            except OSError as write_error:
                logger.warning('Cannot launch gremlin %s: %s', gremlin.gremlin_id, write_error)
                aggregator.add_error(gremlin.gremlin_id, OSError(_node_ids_write_failure_output(write_error)))
                launch_failed_ids.add(gremlin.gremlin_id)
                continue
            test_commands[gremlin.gremlin_id] = test_command

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
    unconfirmed: list[GremlinResult] = []
    for worker_result in aggregator.get_results():
        gremlin_id = worker_result.gremlin_id
        if gremlin_id not in gremlin_by_id:
            continue

        gremlin_result = GremlinResult(
            gremlin=gremlin_by_id[gremlin_id],
            status=worker_result.status,
            killing_test=worker_result.killing_test,
            execution_time_ms=worker_result.execution_time_ms,
            error_output=worker_result.error_output,
            selected_tests=gremlin_tests[gremlin_id],
        )
        if gremlin_id in launch_failed_ids:
            results.append(gremlin_result)
            continue
        unconfirmed.append(gremlin_result)

    results.extend(_confirm_and_cache_pooled_results(unconfirmed, test_commands, gremlin_session, rootdir))

    return results


def _confirm_and_cache_pooled_results(
    unconfirmed: list[GremlinResult],
    test_commands: dict[str, list[str]],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> list[GremlinResult]:
    """Confirm pooled results (collection-kill confirmations prefilled concurrently), then cache them."""
    _prefill_collection_kill_confirmations(
        [(r, _node_ids_for_tests(r.selected_tests, gremlin_session)) for r in unconfirmed], gremlin_session, rootdir
    )
    confirmed: list[GremlinResult] = []
    for unconfirmed_result in unconfirmed:
        confirmed_result = _confirm_pooled_result(
            unconfirmed_result,
            test_commands[unconfirmed_result.gremlin.gremlin_id],
            _node_ids_for_tests(unconfirmed_result.selected_tests, gremlin_session),
            gremlin_session,
            rootdir,
        )
        confirmed.append(confirmed_result)
        _cache_gremlin_result(
            unconfirmed_result.gremlin, unconfirmed_result.selected_tests, confirmed_result, gremlin_session
        )
    return confirmed


def _emit_selection_explainer(gremlin_session: GremlinSession) -> None:
    """Print a selection-drift diagnostic for a single gremlin, then disable the session.

    When ``gremlin_session.explain_gremlin_id`` is set, surfaces everything a
    user needs to see *why* a particular gremlin's covering and selected test
    sets disagree:

    - The covering set (tests whose coverage map contains the mutated line).
    - The selected list (tests the prioritized selector would actually run).
    - The difference in both directions (covering minus selected, selected
      minus runnable-via-``test_node_ids``).
    - For every dropped test, the closest matches in the test-node-ID space
      (via :func:`difflib.get_close_matches` with ``n=3, cutoff=0.7``) plus
      the subprocess-style stripped form, so a reader can spot marker/path
      drift at a glance.

    The function is side-effect heavy on purpose: it emits diagnostic text to
    stdout, then sets ``gremlin_session.enabled = False`` so the per-gremlin
    loops driven by the test run turn into no-ops. It does
    **not** call :func:`sys.exit` or :func:`pytest.exit` — letting pytest
    finish its own session cleanly preserves the user's regular test results
    without masking them behind an early exit code.

    Args:
        gremlin_session: The current gremlin session. Must have
            ``explain_gremlin_id`` set; when ``None`` the function no-ops.
    """
    target_id = gremlin_session.explain_gremlin_id
    if target_id is None:
        return

    _print_terminal_notices(gremlin_session)
    target_gremlin = next(
        (g for g in gremlin_session.gremlins if g.gremlin_id == target_id),
        None,
    )

    if target_gremlin is None:
        skipped_hint = ' Files were skipped (see above).' if gremlin_session.skipped_files else ''
        print(
            f'--gremlin-explain: no gremlin with id {target_id!r} in this session. '
            f'Run with --gremlins (without --gremlin-explain) to see the full list of '
            f'gremlin ids in the progress log.{skipped_hint}'
        )
        gremlin_session.enabled = False
        return

    covering = _covering_tests_for_gremlin(target_gremlin, gremlin_session)
    selected = _selected_test_names_for_gremlin(target_gremlin, gremlin_session)
    runnable = set(gremlin_session.test_node_ids)
    covering_minus_selected = sorted(covering - set(selected))
    selected_minus_runnable = sorted(set(selected) - runnable)

    _print_explainer_header(target_gremlin, covering, selected)

    if gremlin_session.no_coverage_filter:
        print('  Note: coverage filter disabled -- all tests selected (--gremlin-no-coverage-filter).')

    if not covering_minus_selected and not selected_minus_runnable:
        print(
            '  Result: selection is consistent with covering set (no drift). '
            'If this gremlin still survived, the cause is elsewhere (e.g. a weak '
            'assertion in the covering tests).'
        )
        gremlin_session.enabled = False
        return

    runnable_candidates = sorted(runnable)
    _print_dropped_tests(covering_minus_selected, runnable_candidates)
    _print_unrunnable_selections(selected_minus_runnable, runnable_candidates)

    gremlin_session.enabled = False


def _covering_tests_for_gremlin(gremlin: Gremlin, gremlin_session: GremlinSession) -> set[str]:
    """Return the set of tests whose coverage map touches the mutated line."""
    collector = gremlin_session.coverage_collector
    if collector is None:
        return set()
    return collector.coverage_map.get_tests(gremlin.file_path, gremlin.line_number)


def _pluralize_test_count(count: int) -> str:
    """Render a test count with the correctly pluralized noun.

    Examples:
        >>> _pluralize_test_count(0)
        '0 tests'
        >>> _pluralize_test_count(1)
        '1 test'
        >>> _pluralize_test_count(2)
        '2 tests'
    """
    return f'{count} test' if count == 1 else f'{count} tests'


def _print_explainer_header(gremlin: Gremlin, covering: set[str], selected: list[str]) -> None:
    """Print the banner plus the covering and selected lists for the diagnostic."""
    print(f'--gremlin-explain: diagnostic for {gremlin.gremlin_id}')
    print(f'  file: {gremlin.file_path}:{gremlin.line_number}')
    print(f'  Covering set ({_pluralize_test_count(len(covering))}):')
    for key in sorted(covering):
        print(f'    {key!r}')
    print(f'  Selected list ({_pluralize_test_count(len(selected))}):')
    for key in selected:
        print(f'    {key!r}')


def _close_matches_display(needle: str, haystack: list[str]) -> str:
    """Render a comma-separated list of close matches, or a stable fallback."""
    close = difflib.get_close_matches(needle, haystack, n=3, cutoff=0.7)
    return ', '.join(repr(match) for match in close) if close else '<no close match>'


def _print_dropped_tests(dropped: list[str], runnable_candidates: list[str]) -> None:
    """Print the covering-minus-selected breakdown with close-match hints."""
    if not dropped:
        return
    print(f'  Covering minus selected ({len(dropped)} dropped):')
    for key in dropped:
        print(f'    dropped    : {key!r}')
        print(f'    stripped   : {_drop_bracketed_suffix(key)!r}')
        print(f'    close match: {_close_matches_display(key, runnable_candidates)}')


def _print_unrunnable_selections(orphans: list[str], runnable_candidates: list[str]) -> None:
    """Print selections that can't be matched back to ``test_node_ids``."""
    if not orphans:
        return
    print(f'  Selected but not in test_node_ids ({len(orphans)}):')
    for key in orphans:
        print(f'    selected   : {key!r}')
        print(f'    close match: {_close_matches_display(key, runnable_candidates)}')


def _split_gremlins_needing_a_run(
    gremlins: list[Gremlin],
    gremlin_tests: dict[str, list[str]],
    gremlin_session: GremlinSession,
) -> tuple[list[GremlinResult], list[Gremlin]]:
    """Separate gremlins whose verdict is already known from those that must run.

    Pardoned and unrunnable gremlins are settled without running; the rest are looked
    up in the cache. The cache hit and miss counters are updated and the split is
    reported once.

    Args:
        gremlins: The gremlins to split, in run order.
        gremlin_tests: The runnable selection for each gremlin, keyed by gremlin id.
        gremlin_session: The current gremlin session.

    Returns:
        The results known without running, and the gremlins still to test.
    """
    known_results: list[GremlinResult] = []
    gremlins_to_test: list[Gremlin] = []
    settled_without_running = 0

    for gremlin in gremlins:
        settled_result = _immediate_result_if_pardoned(gremlin)
        if settled_result is None:
            settled_result = _immediate_result_if_selection_unrunnable(gremlin, gremlin_session)
        if settled_result is not None:
            known_results.append(settled_result)
            settled_without_running += 1
            continue
        cached_result = _check_cache_for_gremlin(gremlin, gremlin_tests[gremlin.gremlin_id], gremlin_session)
        if cached_result is not None:
            gremlin_session.cache_hits += 1
            known_results.append(cached_result)
            continue
        if gremlin_session.cache_enabled:
            gremlin_session.cache_misses += 1
        gremlins_to_test.append(gremlin)

    if known_results:
        print(
            _format_cache_report(
                cache_hits=len(known_results) - settled_without_running,
                settled_without_running=settled_without_running,
                to_test=len(gremlins_to_test),
            )
        )
    return known_results, gremlins_to_test


def _format_cache_report(*, cache_hits: int, settled_without_running: int, to_test: int) -> str:
    """Describe how the gremlins were split before execution starts.

    Pardoned and unrunnable gremlins get their verdict without running, so they
    are reported apart from genuine cache hits.

    Examples:
        >>> _format_cache_report(cache_hits=3, settled_without_running=0, to_test=2)
        'pytest-gremlins: 3 gremlins from cache, 2 to test'
        >>> _format_cache_report(cache_hits=0, settled_without_running=4, to_test=0)
        'pytest-gremlins: 0 gremlins from cache, 4 settled without running, 0 to test'
    """
    settled = f', {settled_without_running} settled without running' if settled_without_running else ''
    return f'pytest-gremlins: {cache_hits} gremlins from cache{settled}, {to_test} to test'


def _drop_bracketed_suffix(nodeid: str) -> str:
    """Return ``nodeid`` with a trailing ``' [...]'`` marker suffix removed.

    Shares its rule (:func:`strip_marker_suffix`) with the coverage subprocess
    bootstrap (`_strip_nodeid_markers`).  Used only by
    :func:`_emit_selection_explainer` to show the reader the shape the
    subprocess would record for a drifted key.

    Examples:
        >>> _drop_bracketed_suffix('tests/test_foo.py::test_bar [SMALL]')
        'tests/test_foo.py::test_bar'
        >>> _drop_bracketed_suffix('tests/test_foo.py::test_bar')
        'tests/test_foo.py::test_bar'
    """
    return strip_marker_suffix(nodeid)


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
    base_test_command = _build_test_command(
        gremlin_session.instrumented_dir,
        gremlin_session.preserved_addopts,
        xdist_loaded=gremlin_session.xdist_loaded,
        xdist_loader_options=gremlin_session.xdist_loader_options,
        doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
        rerun_options=gremlin_session.rerun_options,
        pytest_cov_options=gremlin_session.pytest_cov_options,
    )

    for i, gremlin in enumerate(gremlin_session.gremlins, 1):
        pardoned_result = _immediate_result_if_pardoned(gremlin)
        if pardoned_result is not None:
            results.append(pardoned_result)
            continue
        selected_tests = _select_tests_for_gremlin_prioritized(gremlin, gremlin_session)
        unrunnable_result = _immediate_result_if_selection_unrunnable(gremlin, gremlin_session)
        if unrunnable_result is not None:
            results.append(unrunnable_result)
            continue
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

        try:
            test_command = _build_filtered_test_command(
                base_test_command,
                selected_tests,
                gremlin_session,
            )
        except OSError as write_error:
            logger.warning('Cannot launch gremlin %s: %s', gremlin.gremlin_id, write_error)
            results.append(
                GremlinResult(
                    gremlin=gremlin,
                    status=GremlinResultStatus.ERROR,
                    error_output=_node_ids_write_failure_output(write_error),
                    selected_tests=selected_tests,
                )
            )
            continue
        gremlin_result = _test_gremlin(
            gremlin,
            test_command,
            rootdir,
            gremlin_session.instrumented_dir,
            timeout=gremlin_session.mutant_timeout,
        )
        # Attach selected tests for debuggability in reports
        gremlin_result = dataclass_replace(gremlin_result, selected_tests=selected_tests)
        gremlin_result = _confirm_kill(
            gremlin_result, _node_ids_for_tests(selected_tests, gremlin_session), gremlin_session, rootdir
        )

        # Cache the result for next run
        _cache_gremlin_result(gremlin, selected_tests, gremlin_result, gremlin_session)

        results.append(gremlin_result)

    return results


def _node_id_for_test(test_name: str, gremlin_session: GremlinSession) -> str:
    """Resolve a selected test name to its node id, or '' when it has none.

    Test names can be in different formats (simple function, module.function, TestClass.method), so this
    tries variations to find the corresponding node ID.
    """
    node_id = gremlin_session.test_node_ids.get(test_name, '')
    if not node_id:
        simple_name = test_name.rsplit('.', maxsplit=1)[-1]
        node_id = gremlin_session.test_node_ids.get(simple_name, '')
    if not node_id:
        # Coverage map may use bare function names (old-format dynamic_context)
        # while test_node_ids is keyed by full node ID.  Use the reverse index
        # for O(1) lookup instead of O(n) linear suffix scan.
        candidates = gremlin_session.test_name_to_node_ids.get(test_name, [])
        if not candidates:
            candidates = gremlin_session.test_name_to_node_ids.get(test_name.rsplit('.', maxsplit=1)[-1], [])
        if candidates:
            node_id = candidates[0]
    return node_id


def _build_test_hashes_for_gremlin(
    selected_tests: Sequence[str],
    gremlin_session: GremlinSession,
) -> dict[str, str]:
    """Build test hashes for the tests that cover a gremlin.

    Maps test names to their file content hashes.

    Args:
        selected_tests: Sequence of test names that cover the gremlin.
        gremlin_session: The current gremlin session with test metadata.

    Returns:
        Dictionary mapping test names to their file content hashes.
    """
    test_hashes: dict[str, str] = {}
    for test_name in selected_tests:
        node_id = _node_id_for_test(test_name, gremlin_session)
        if '::' in node_id:
            file_hash = gremlin_session.test_hashes.get(node_id.split('::')[0])
            if file_hash is not None:
                test_hashes[test_name] = file_hash

    return test_hashes


def _selection_has_unhashed_test_file(selected_tests: Sequence[str], gremlin_session: GremlinSession) -> bool:
    """Whether a selected test has no node id, or lives in a file that could not be hashed (outside rootdir).

    A cache key built without that file's hash would replay a verdict after the test changed.
    """
    for test_name in selected_tests:
        node_id = _node_id_for_test(test_name, gremlin_session)
        if '::' not in node_id or node_id.split('::')[0] not in gremlin_session.test_hashes:
            return True
    return False


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

    if _selection_has_unhashed_test_file(selected_tests, gremlin_session):
        return None

    test_hashes = _build_test_hashes_for_gremlin(selected_tests, gremlin_session)

    cached = gremlin_session.cache.get_cached_result(
        gremlin_id=gremlin.gremlin_id,
        source_hash=source_hash,
        test_hashes=test_hashes,
        mutant_timeout=gremlin_session.mutant_timeout,
        optimize_level=subprocess_optimize_level(os.environ),
        rerun_budget=gremlin_session.rerun_budget,
        rerun_settings=gremlin_session.rerun_cache_settings,
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

    # A verdict scored while load failures were unattributable, or downgraded because the unmutated
    # selection does not load, is too slow without a mutant, or cannot be launched to confirm a timeout,
    # or was aborted because pytest's assertion-rewrite API changed (#617), depends on a harness or config problem
    # the user is told to fix; replaying it from a warm cache after the fix would keep reporting stale errors.
    if not gremlin_session.load_failures_attributable:
        return
    uncacheable_error_prefixes = (
        SELECTION_FAILS_TO_LOAD_PREFIX,
        TIMEOUT_NOT_CONFIRMED_PREFIX,
        TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX,
        REWRITE_API_BROKEN_PREFIX,
    )
    if (result.error_output or '').startswith(uncacheable_error_prefixes):
        return

    source_hash = gremlin_session.source_hashes.get(gremlin.file_path, '')
    if not source_hash:
        return

    if _selection_has_unhashed_test_file(selected_tests, gremlin_session):
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
        mutant_timeout=gremlin_session.mutant_timeout,
        optimize_level=subprocess_optimize_level(os.environ),
        rerun_budget=gremlin_session.rerun_budget,
        rerun_settings=gremlin_session.rerun_cache_settings,
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


def _selected_test_names_for_gremlin(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> list[str]:
    """Select the test names for a gremlin, ordered by specificity (most specific first).

    Uses the PrioritizedSelector to return tests in an order that maximizes
    the chance of catching the mutation quickly. Tests covering fewer lines
    are considered more specific and run first.

    When coverage-guided selection finds no covering tests, falls back to
    running all tests. This handles module-level code (class attribute defaults,
    module constants) that executes at import time before any test function
    runs. Coverage.py records these lines under the empty context, which isn't
    associated with any specific test.

    The names are not yet checked against ``test_node_ids``; see
    :func:`_select_tests_for_gremlin_prioritized` for the runnable subset.

    Args:
        gremlin: The gremlin to select tests for.
        gremlin_session: The current gremlin session.

    Returns:
        List of test names ordered by specificity (most specific first).
    """
    if gremlin_session.no_coverage_filter:
        return list(gremlin_session.test_node_ids.keys())

    if gremlin_session.prioritized_selector is None:
        return list(gremlin_session.test_node_ids.keys())

    selected = gremlin_session.prioritized_selector.select_tests_prioritized(gremlin)
    if not selected:
        return list(gremlin_session.test_node_ids.keys())

    return selected


def _select_tests_for_gremlin_prioritized(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> list[str]:
    """Select the runnable tests for a gremlin, ordered by specificity (most specific first).

    A selected name with no entry in ``test_node_ids`` cannot be passed to pytest, so it is left
    out and recorded in ``gremlin_session.unmapped_selections`` instead of vanishing silently. The
    command, the cache key, the confirmations and the result all use this same list, so none of
    them can disagree about what the gremlin ran. When every selected name is dropped the result
    is empty, and :func:`_immediate_result_if_selection_unrunnable` abstains: an empty list must
    never reach pytest, where it would run the whole suite and score a verdict the selection did
    not back.

    Args:
        gremlin: The gremlin to select tests for.
        gremlin_session: The current gremlin session.

    Returns:
        The selected test names that have a node id, in selection order.
    """
    selected = _selected_test_names_for_gremlin(gremlin, gremlin_session)
    runnable = [name for name in selected if name in gremlin_session.test_node_ids]
    dropped = [name for name in selected if name not in gremlin_session.test_node_ids]
    gremlin_session.unmapped_selections.pop(gremlin.gremlin_id, None)
    gremlin_session.unrunnable_gremlin_ids.discard(gremlin.gremlin_id)
    if dropped:
        gremlin_session.unmapped_selections[gremlin.gremlin_id] = dropped
        if not runnable:
            gremlin_session.unrunnable_gremlin_ids.add(gremlin.gremlin_id)
    return runnable


def _immediate_result_if_selection_unrunnable(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> GremlinResult | None:
    """Return an ERROR result when every test selected for the gremlin lacks a node id, else None.

    Called at the top of every execution loop, right after the pardon check and once the gremlin's
    selection has been made. Such a gremlin has no command to run, so no verdict can be backed by a
    test: it abstains with an error naming the dropped tests.

    Args:
        gremlin: The gremlin to check.
        gremlin_session: The current gremlin session, holding the dropped selections.

    Returns:
        A GremlinResult with ERROR status when the whole selection was dropped, otherwise None.
    """
    if gremlin.gremlin_id not in gremlin_session.unrunnable_gremlin_ids:
        return None
    dropped = gremlin_session.unmapped_selections[gremlin.gremlin_id]
    shown_ids = ', '.join(dropped[:MAX_SELECTION_IDS_IN_MESSAGE])
    hidden_count = len(dropped) - MAX_SELECTION_IDS_IN_MESSAGE
    overflow_note = f' (and {hidden_count} more)' if hidden_count > 0 else ''
    return GremlinResult(
        gremlin=gremlin,
        status=GremlinResultStatus.ERROR,
        error_output=(
            f'{UNMAPPED_SELECTION_PREFIX}: {len(dropped)} selected test(s) have no pytest node id, '
            f'so none could run: {shown_ids}{overflow_note}'
        ),
    )


def _report_unmapped_selections(gremlin_session: GremlinSession) -> None:
    """Report once per run that coverage-selected tests were not run because they have no node id.

    Written to stderr rather than raised through ``warnings.warn``: this runs in ``pytest_sessionfinish``,
    where a project's ``filterwarnings = error`` would turn the report into a crash after a green run (#543).
    """
    unmapped = gremlin_session.unmapped_selections
    if not unmapped:
        return
    dropped_names = {name for names in unmapped.values() for name in names}
    example = next(iter(unmapped.values()))[0]
    print(
        f'pytest-gremlins: {len(dropped_names)} selected test(s) for {len(unmapped)} gremlin(s) have no pytest '
        f'node id and were not run, e.g. {example}. Gremlins left with no runnable test are scored ERROR.',
        file=sys.stderr,
    )


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


def _node_ids_write_failure_output(error: OSError) -> str:
    """Describe a failed write of the node-ids file for a gremlin's ``error_output``."""
    return f'Could not write the node ids file for the gremlin test command: {error}'[:2000]


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
        Command list that runs the selected node IDs in the same order. They travel in a file named on the
        command line, so a full-suite selection cannot exceed Windows' 32,767 character limit (#485); without an
        instrumented directory to hold the file they are appended to the command.
    """
    return command_with_node_ids_file(
        base_command,
        _node_ids_for_tests(selected_tests, gremlin_session),
        gremlin_session.instrumented_dir,
    )


def _build_test_command(
    instrumented_dir: Path | None,
    preserved_addopts: str = '',
    *,
    xdist_loaded: bool = False,
    xdist_loader_options: Sequence[str] = (),
    doctest_ini_overrides: Sequence[str] = (),
    rerun_options: Sequence[str] = (),
    pytest_cov_options: Sequence[str] = (),
) -> list[str]:
    """Build the command to run tests.

    If an instrumented directory is provided, uses the bootstrap script
    to register import hooks before running pytest. Otherwise, runs
    pytest directly.

    ``--no-cov`` arrives through ``pytest_cov_options`` and only when gremlin runs have pytest-cov
    loaded, so that runs without the plugin do not receive an unknown CLI flag (which causes pytest
    exit-code 4).

    Args:
        instrumented_dir: Directory containing bootstrap infrastructure, or None.
        preserved_addopts: The project's ``addopts`` with pytest-cov flags stripped
            (see :func:`_addopts_without_cov`), passed through as ``-o addopts=<...>``
            so collection-affecting options such as ``--import-mode=importlib`` survive
            into the subprocess. Defaults to ``''`` (clear all addopts). xdist options
            are dropped (see :func:`~pytest_gremlins.xdist_options.addopts_without_xdist`)
            so the tests run in the bootstrap process, where the gremlin import hook lives.
        xdist_loaded: Whether pytest-xdist is loaded in the main session.  If so, ``-n 0`` is
            appended as a second layer: argparse keeps the last value, so no spelling of ``-n``
            in ``addopts`` or ``PYTEST_ADDOPTS`` (for example a clustered ``-xn 2``, which the
            token stripper does not recognise) can distribute the run.  xdist itself stays
            loaded, so ``worker_id`` still works.  Without xdist the flag would be rejected as
            unrecognized, so it is omitted.
        xdist_loader_options: The ``-p`` loader for gremlin runs that start with autoload disabled (see
            :func:`_xdist_options_for`), placed before ``-n 0`` so the option has a plugin to parse it.
        doctest_ini_overrides: The session's resolved doctest ini values as ``-o key=value`` argument pairs
            (see :func:`_doctest_ini_overrides`), kept outside ``addopts`` because pytest before 9.1 ignores a
            ``-o`` nested in an ``addopts`` value (issue #719).
        rerun_options: pytest-rerunfailures options typed on the command line (see
            :func:`~pytest_gremlins.rerun_options.rerun_options_in`), appended last so they win over
            ``addopts`` as they do in the baseline run.  A flaky test then has to fail on every
            attempt before it can zap a gremlin (issue #546).
        pytest_cov_options: The ``--no-cov`` flag, preceded by a ``-p`` loader when gremlin runs start with
            autoload disabled (see :func:`_pytest_cov_options_for`); empty when they do not load pytest-cov.

    Returns:
        Command list to run tests.
    """
    gremlin_addopts = addopts_without_xdist(preserved_addopts)
    if instrumented_dir is not None:
        bootstrap_script = instrumented_dir / 'gremlin_bootstrap.py'
        command = [
            sys.executable,
            str(bootstrap_script),
            '-x',
            '--tb=no',
            '-q',
            '-o',
            f'addopts={gremlin_addopts}',
            *doctest_ini_overrides,
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
            f'addopts={gremlin_addopts}',
            *doctest_ini_overrides,
        ]

    command.extend(pytest_cov_options)

    if xdist_loaded:
        command.extend([*xdist_loader_options, '-n', '0'])

    command.extend(rerun_options)

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
    *,
    timeout: int,
) -> GremlinResult:
    """Test a single gremlin and record how long the run took.

    The elapsed time lets the incremental cache reuse the verdict under a different mutant timeout (#567).

    Args:
        gremlin: The gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory of the project.
        instrumented_dir: Directory containing bootstrap infrastructure.
        timeout: Seconds the test run may take before the gremlin is reported as a timeout.

    Returns:
        Result of testing the gremlin, with ``execution_time_ms`` set.
    """
    started = time.monotonic()
    result = _run_gremlin_subprocess(gremlin, test_command, rootdir, instrumented_dir, timeout=timeout)
    elapsed_ms = (time.monotonic() - started) * MILLISECONDS_PER_SECOND
    return dataclass_replace(result, execution_time_ms=elapsed_ms)


def _run_gremlin_subprocess(
    gremlin: Gremlin,
    test_command: list[str],
    rootdir: Path,
    instrumented_dir: Path | None,
    *,
    timeout: int,
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
        timeout: Seconds the test run may take before the gremlin is reported as a timeout.

    Returns:
        Result of testing the gremlin.
    """
    env = env_without_xdist_addopts(os.environ)
    env[ACTIVE_GREMLIN_ENV_VAR] = gremlin.gremlin_id
    env['GREMLIN_ROOTDIR'] = str(rootdir)

    if instrumented_dir is not None:
        sources_file = instrumented_dir / 'sources.json'
        env[GREMLIN_SOURCES_ENV_VAR] = str(sources_file)
    export_spawn_hook(env)

    # Single routing point for the lightweight runner. It always returns None while the runner is
    # disabled (#538), so every gremlin runs through the pytest bootstrap.
    lightweight_cmd = build_lightweight_command(test_command, env)
    effective_command = lightweight_cmd if lightweight_cmd is not None else test_command

    try:
        subprocess_outcome = subprocess.run(  # Intentional: runs pytest test commands
            effective_command,
            cwd=str(rootdir),
            env=env,
            capture_output=True,
            timeout=timeout,
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
        if subprocess_outcome.returncode == GREMLIN_COLLECTION_FAILED_EXIT_CODE:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ZAPPED,
                killing_test=COLLECTION_KILLING_TEST,
            )
        error_output = describe_runner_error(subprocess_outcome.returncode, subprocess_outcome.stderr)
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


def _write_html_report(
    score: MutationScore, rootdir: Path, html_dir: Path | None = None, *, skipped_files: dict[str, str] | None = None
) -> Path:
    """Write HTML report to file.

    Args:
        score: The MutationScore to write.
        rootdir: Root directory of the project.
        html_dir: Custom output directory, or ``None`` for the default
            ``<rootdir>/coverage/gremlins/`` location.
        skipped_files: Paths and reasons for files that could not be instrumented.

    Returns:
        Path to the written HTML report.
    """
    reporter = HtmlReporter()
    output_path = resolve_html_output_path(rootdir=rootdir, html_dir=html_dir)
    reporter.write_report(score, output_path, skipped_files=skipped_files)
    return output_path


def _write_json_report(score: MutationScore, rootdir: Path, *, skipped_files: dict[str, str] | None = None) -> Path:
    """Write JSON report to file.

    Args:
        score: The MutationScore to write.
        rootdir: Root directory of the project.
        skipped_files: Paths and reasons for files that could not be instrumented.

    Returns:
        Path to the written JSON report.
    """
    reporter = JsonReporter()
    # TODO(#308): add --gremlins-json-path flag for parity with --gremlins-html-dir
    output_path = rootdir / 'coverage' / 'gremlins' / 'gremlins.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    reporter.write_report(score, output_path, skipped_files=skipped_files)
    return output_path


def _write_empty_run_report(terminalreporter: pytest.TerminalReporter, gremlin_session: GremlinSession) -> None:
    """Explain a run that produced no gremlins: files skipped, nothing found, or no paths discovered."""
    terminalreporter.write_sep('=', 'pytest-gremlins mutation report')
    terminalreporter.write_line('')
    if gremlin_session.skipped_files:
        terminalreporter.write_line(f'{len(gremlin_session.skipped_files)} file(s) skipped and not mutation tested:')
        for skipped_path, reason in gremlin_session.skipped_files.items():
            terminalreporter.write_line(f'  - {_neutralize_control_characters(skipped_path)} ({reason})')
    elif gremlin_session.target_paths:
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


def _write_file_reports(
    terminalreporter: pytest.TerminalReporter,
    gremlin_session: GremlinSession,
    config: pytest.Config,
    score: MutationScore,
) -> None:
    """Write the HTML and JSON reports the session asked for and say where they went."""
    rootdir = _get_rootdir(config)

    if 'html' in gremlin_session.report_formats:
        raw_html_dir = config.getoption('gremlins_html_dir', default=None)
        html_dir = Path(raw_html_dir) if raw_html_dir is not None else None
        try:
            report_path = _write_html_report(
                score, rootdir=rootdir, html_dir=html_dir, skipped_files=gremlin_session.skipped_files
            )
            terminalreporter.write_line(f'HTML report written to: {report_path}')
        except OSError as exc:
            logger.warning('Failed to write HTML report: %s', exc)
            terminalreporter.write_line(f'HTML report write failed: {exc}')

    if 'json' in gremlin_session.report_formats:
        try:
            json_path = _write_json_report(score, rootdir=rootdir, skipped_files=gremlin_session.skipped_files)
            terminalreporter.write_line(f'JSON report written to: {json_path}')
        except OSError as exc:
            logger.warning('Failed to write JSON report: %s', exc)
            terminalreporter.write_line(f'JSON report write failed: {exc}')


def pytest_terminal_summary(  # noqa: C901, PLR0912, PLR0915
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,  # noqa: ARG001
    config: pytest.Config,
) -> None:
    """Add mutation testing results to terminal output."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    for notice in gremlin_session.terminal_notices:
        terminalreporter.write_line(notice)

    score = MutationScore.from_results(
        gremlin_session.results,
        mutant_timeout=gremlin_session.mutant_timeout,
        mutant_attempt_timeout=gremlin_session.mutant_attempt_timeout,
    )

    if not gremlin_session.gremlins:
        # A run with no gremlins still writes (zero-gremlin) reports, so a stale score is overwritten.
        # Write them first so their locations print before the empty-run report's closing separator.
        _write_file_reports(terminalreporter, gremlin_session, config, score)
        _write_empty_run_report(terminalreporter, gremlin_session)
        return

    _write_file_reports(terminalreporter, gremlin_session, config, score)

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
        if score.timeout_warning is not None:
            terminalreporter.write_line(f'Warning: {score.timeout_warning}')

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


@pytest.hookimpl(hookwrapper=True)
def pytest_unconfigure(config: pytest.Config) -> collections.abc.Generator[None, None, None]:
    """Clean up the session this Config owns and restore the one it displaced."""
    yield
    if any(configured is config for configured in _configured_configs):
        _release_session(config)
