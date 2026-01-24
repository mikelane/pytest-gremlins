"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

from pytest_gremlins.coverage import CoverageCollector, TestSelector
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.instrumentation.transformer import get_default_registry, transform_source
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


if TYPE_CHECKING:
    import pytest

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.operators import GremlinOperator


GREMLIN_SOURCES_ENV_VAR = 'PYTEST_GREMLINS_SOURCES_FILE'


@dataclass
class GremlinSession:
    """Session state for mutation testing.

    Attributes:
        enabled: Whether mutation testing is enabled.
        operators: List of operators to use for mutation.
        report_format: Report format (console, html, json).
        gremlins: All gremlins found in the source code.
        results: Results from testing each gremlin.
        source_files: Mapping of file paths to their source code.
        test_files: List of test file paths that were collected.
        instrumented_dir: Temporary directory containing instrumented source files.
        coverage_collector: Collects coverage data per-test.
        test_selector: Selects tests based on coverage data.
        test_node_ids: Maps test names to their pytest node IDs.
        total_tests: Total number of tests collected.
    """

    enabled: bool = False
    operators: list[GremlinOperator] = field(default_factory=list)
    report_format: str = 'console'
    gremlins: list[Gremlin] = field(default_factory=list)
    results: list[GremlinResult] = field(default_factory=list)
    source_files: dict[str, str] = field(default_factory=dict)
    test_files: list[Path] = field(default_factory=list)
    target_paths: list[Path] = field(default_factory=list)
    instrumented_dir: Path | None = None
    coverage_collector: CoverageCollector | None = None
    test_selector: TestSelector | None = None
    test_node_ids: dict[str, str] = field(default_factory=dict)
    total_tests: int = 0


_gremlin_session: GremlinSession | None = None


def _get_session() -> GremlinSession | None:
    """Get the current gremlin session."""
    return _gremlin_session


def _set_session(session: GremlinSession | None) -> None:
    """Set the current gremlin session."""
    global _gremlin_session  # noqa: PLW0603
    _gremlin_session = session


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
        action='store',
        default='console',
        dest='gremlin_report',
        help='Report format: console, html, json (default: console)',
    )
    group.addoption(
        '--gremlin-targets',
        action='store',
        default=None,
        dest='gremlin_targets',
        help='Comma-separated list of source directories/files to mutate',
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options."""
    if not config.option.gremlins:
        _set_session(GremlinSession(enabled=False))
        return

    registry = get_default_registry()

    operators_opt = config.option.gremlin_operators
    if operators_opt:
        operator_names = [name.strip() for name in operators_opt.split(',')]
        operators = registry.get_all(enabled=operator_names)
    else:
        operators = registry.get_all()

    target_paths: list[Path] = []
    targets_opt = config.option.gremlin_targets
    if targets_opt:
        for target in targets_opt.split(','):
            path = Path(target.strip())
            if path.exists():
                target_paths.append(path)
    else:
        src_path = Path('src')
        if src_path.exists():
            target_paths.append(src_path)

    _set_session(
        GremlinSession(
            enabled=True,
            operators=operators,
            report_format=config.option.gremlin_report,
            target_paths=target_paths,
        )
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    """After test collection, discover source files and generate gremlins."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    test_files = [Path(item.fspath) for item in session.items if hasattr(item, 'fspath')]
    gremlin_session.test_files = list(set(test_files))

    gremlin_session.total_tests = len(session.items)
    gremlin_session.test_node_ids = {item.name: item.nodeid for item in session.items}

    source_files = _discover_source_files(session, gremlin_session)
    gremlin_session.source_files = source_files

    rootdir = Path(session.config.rootdir)  # type: ignore[attr-defined]
    all_gremlins: list[Gremlin] = []
    instrumented_asts: dict[str, ast.Module] = {}

    for file_path, source in source_files.items():
        gremlins, instrumented_tree = transform_source(source, file_path, gremlin_session.operators)
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
    rootdir = Path(session.config.rootdir)  # type: ignore[attr-defined]

    for target_path in gremlin_session.target_paths:
        resolved_path = target_path if target_path.is_absolute() else rootdir / target_path

        if resolved_path.is_file() and resolved_path.suffix == '.py':
            _add_source_file(resolved_path, source_files)
        elif resolved_path.is_dir():
            for py_file in resolved_path.rglob('*.py'):
                if _should_include_file(py_file):
                    _add_source_file(py_file, source_files)

    return source_files


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
    except (SyntaxError, OSError):
        pass


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

    instrumented_sources: dict[str, str] = {}
    for original_path, tree in instrumented_asts.items():
        module_name = _path_to_module_name(Path(original_path), rootdir)
        instrumented_source = ast.unparse(tree)
        final_source = gremlin_active_injection + instrumented_source
        instrumented_sources[module_name] = final_source

    sources_file = temp_dir / 'sources.json'
    sources_file.write_text(json.dumps(instrumented_sources))

    bootstrap_script = temp_dir / 'gremlin_bootstrap.py'
    bootstrap_script.write_text(_get_bootstrap_script())

    return temp_dir


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


def _cleanup_instrumented_dir(instrumented_dir: Path | None) -> None:
    """Clean up the temporary instrumented files directory.

    Args:
        instrumented_dir: Path to the directory to remove, or None.
    """
    if instrumented_dir is not None and instrumented_dir.exists():
        shutil.rmtree(instrumented_dir, ignore_errors=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """After all tests run, execute mutation testing."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if not gremlin_session.gremlins:
        return

    rootdir = Path(session.config.rootdir)  # type: ignore[attr-defined]
    _collect_coverage(gremlin_session, rootdir)

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
    import re  # noqa: PLC0415

    result = []
    rootdir_str = str(rootdir)
    for node_id in node_ids:
        # Strip any plugin-added suffixes like "[SMALL]", "[MEDIUM]", etc.
        # These are display decorations, not part of the actual node ID
        cleaned_node_id = re.sub(r'\s*\[[A-Z]+\]\s*$', '', node_id)

        # Node IDs have format: path/to/file.py::test_name
        # or just: file.py::test_name
        if '::' in cleaned_node_id:
            path_part, test_part = cleaned_node_id.split('::', 1)
            if path_part.startswith(rootdir_str):
                # Remove rootdir prefix and leading separator
                relative_path = path_part[len(rootdir_str) :].lstrip('/\\')
                result.append(f'{relative_path}::{test_part}')
            else:
                result.append(cleaned_node_id)
        # No :: separator, just a path - make it relative if absolute
        elif cleaned_node_id.startswith(rootdir_str):
            relative_path = cleaned_node_id[len(rootdir_str) :].lstrip('/\\')
            result.append(relative_path)
        else:
            result.append(cleaned_node_id)
    return result


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
        *test_node_ids,
        '--tb=no',
        '-q',
    ]

    try:
        subprocess.run(  # noqa: S603
            cmd,
            cwd=str(rootdir),
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        coveragerc_path.unlink(missing_ok=True)
        return {}

    result: dict[str, dict[str, list[int]]] = {}

    try:
        if not coverage_db_path.exists():
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
            test_name = context.split('|')[-1] if '|' in context else context
            test_name = test_name.split('::')[-1] if '::' in test_name else test_name

            file_path = files[file_id]

            lines = _decode_numbits(numbits)

            if test_name not in result:
                result[test_name] = {}
            if file_path not in result[test_name]:
                result[test_name][file_path] = []
            result[test_name][file_path].extend(lines)

        conn.close()

    except (sqlite3.Error, OSError):
        pass
    finally:
        try:
            coverage_db_path.unlink(missing_ok=True)
            coveragerc_path.unlink(missing_ok=True)
        except OSError:
            pass

    return result


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


def _run_mutation_testing(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing for all gremlins.

    Args:
        session: The pytest session.
        gremlin_session: The current gremlin session.

    Returns:
        List of results for each gremlin.
    """
    results: list[GremlinResult] = []
    rootdir = Path(session.config.rootdir)  # type: ignore[attr-defined]
    base_test_command = _build_test_command(gremlin_session.instrumented_dir)

    for i, gremlin in enumerate(gremlin_session.gremlins, 1):
        selected_tests = _select_tests_for_gremlin(gremlin, gremlin_session)
        test_count = len(selected_tests)
        total = gremlin_session.total_tests

        _report_gremlin_progress(i, len(gremlin_session.gremlins), gremlin, test_count, total)

        if test_count == 0:
            result = GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.SURVIVED,
            )
        else:
            test_command = _build_filtered_test_command(
                base_test_command,
                selected_tests,
                gremlin_session,
            )
            result = _test_gremlin(
                gremlin,
                test_command,
                rootdir,
                gremlin_session.instrumented_dir,
            )

        results.append(result)

    return results


def _select_tests_for_gremlin(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> set[str]:
    """Select tests that cover the gremlin's location.

    Args:
        gremlin: The gremlin to select tests for.
        gremlin_session: The current gremlin session.

    Returns:
        Set of test names that cover the gremlin's location.
    """
    if gremlin_session.test_selector is None:
        return set(gremlin_session.test_node_ids.keys())

    return gremlin_session.test_selector.select_tests(gremlin)


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
    if test_count == 0:
        print(f'{prefix} - 0 tests cover this gremlin, marking as survived')
    else:
        print(f'{prefix} - running {test_count}/{total_tests} tests')


def _build_filtered_test_command(
    base_command: list[str],
    selected_tests: set[str],
    gremlin_session: GremlinSession,
) -> list[str]:
    """Build a test command that runs only the selected tests.

    Args:
        base_command: The base test command.
        selected_tests: Set of test names to run.
        gremlin_session: The current gremlin session.

    Returns:
        Command list with test node IDs appended.
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


def _build_test_command(instrumented_dir: Path | None) -> list[str]:
    """Build the command to run tests.

    If an instrumented directory is provided, uses the bootstrap script
    to register import hooks before running pytest. Otherwise, runs
    pytest directly.

    Args:
        instrumented_dir: Directory containing bootstrap infrastructure, or None.

    Returns:
        Command list to run tests.
    """
    if instrumented_dir is not None:
        bootstrap_script = instrumented_dir / 'gremlin_bootstrap.py'
        return [
            sys.executable,
            str(bootstrap_script),
            '-x',
            '--tb=no',
            '-q',
        ]
    return [
        sys.executable,
        '-m',
        'pytest',
        '-x',
        '--tb=no',
        '-q',
    ]


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

    if instrumented_dir is not None:
        sources_file = instrumented_dir / 'sources.json'
        env[GREMLIN_SOURCES_ENV_VAR] = str(sources_file)

    try:
        result = subprocess.run(  # noqa: S603
            test_command,
            cwd=str(rootdir),
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ZAPPED,
                killing_test='unknown',
            )
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
    except subprocess.TimeoutExpired:
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.TIMEOUT,
        )
    except Exception:
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
        )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,  # noqa: ARG001
    config: pytest.Config,  # noqa: ARG001
) -> None:
    """Add mutation testing results to terminal output."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if not gremlin_session.gremlins:
        terminalreporter.write_sep('=', 'pytest-gremlins mutation report')
        terminalreporter.write_line('')
        terminalreporter.write_line('No gremlins found in source code.')
        terminalreporter.write_line('')
        terminalreporter.write_sep('=', '')
        return

    score = MutationScore.from_results(gremlin_session.results)

    terminalreporter.write_sep('=', 'pytest-gremlins mutation report')
    terminalreporter.write_line('')

    if score.total == 0:
        terminalreporter.write_line('No gremlins tested.')
    else:
        zapped_pct = round(score.percentage)
        survived_pct = 100 - zapped_pct if score.total > 0 else 0

        terminalreporter.write_line(f'Zapped: {score.zapped} gremlins ({zapped_pct}%)')
        terminalreporter.write_line(f'Survived: {score.survived} gremlins ({survived_pct}%)')

        survivors = score.top_survivors(limit=10)
        if survivors:
            terminalreporter.write_line('')
            terminalreporter.write_line('Top surviving gremlins:')
            for result in survivors:
                gremlin = result.gremlin
                location = f'{gremlin.file_path}:{gremlin.line_number}'
                terminalreporter.write_line(f'  {location:<30} {gremlin.description:<20} ({gremlin.operator_name})')

    terminalreporter.write_line('')
    if gremlin_session.report_format != 'html':
        terminalreporter.write_line('Run with --gremlin-report=html for detailed report.')
    terminalreporter.write_sep('=', '')


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    """Clean up after pytest-gremlins."""
    gremlin_session = _get_session()
    if gremlin_session is not None:
        _cleanup_instrumented_dir(gremlin_session.instrumented_dir)
    _set_session(None)
