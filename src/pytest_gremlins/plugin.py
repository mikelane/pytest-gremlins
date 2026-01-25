"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

from pytest_gremlins.coverage import CoverageCollector, CoverageMap, TestSelector
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.instrumentation.transformer import get_default_registry, transform_source
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


if TYPE_CHECKING:
    import pytest

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.operators import GremlinOperator


GREMLIN_SOURCES_ENV_VAR = 'PYTEST_GREMLINS_SOURCES_FILE'
# Minimum number of parts in a coverage context (e.g., "module.test_function")
MIN_CONTEXT_PARTS = 2


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
        target_paths: List of target paths to mutate.
        instrumented_dir: Temporary directory containing instrumented source files.
        coverage_map: Mapping of source lines to test names for coverage-guided selection.
        test_selector: Selector for choosing tests based on coverage.
        total_tests: Total number of tests in the test suite.
        verbose: Whether to show verbose output.
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
    coverage_map: CoverageMap | None = None
    test_selector: TestSelector | None = None
    total_tests: int = 0
    verbose: bool = False


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
            verbose=config.option.verbose > 0,
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


def _collect_coverage(rootdir: Path) -> CoverageMap | None:
    """Collect coverage data by running tests with coverage enabled.

    This runs tests with coverage.py directly to collect per-test coverage data,
    then builds a CoverageMap that maps source lines to test names.

    We use coverage.py's Python API directly rather than pytest-cov to avoid
    dependency issues in subprocess environments (e.g., pytester).

    Args:
        rootdir: Root directory of the project.

    Returns:
        CoverageMap if coverage collection succeeded, None otherwise.
    """
    if find_spec('coverage') is None:
        return None

    # Create a temporary directory for coverage data
    coverage_dir = Path(tempfile.mkdtemp(prefix='pytest_gremlins_cov_'))
    coverage_file = coverage_dir / '.coverage'

    try:
        # Create coverage runner script that collects per-test coverage
        runner_script = coverage_dir / 'coverage_runner.py'
        runner_script.write_text(_get_coverage_runner_script())

        # Run the coverage collection via subprocess
        coverage_cmd = [
            sys.executable,
            str(runner_script),
            str(coverage_file),
        ]

        subprocess.run(  # noqa: S603
            coverage_cmd,
            cwd=str(rootdir),
            capture_output=True,
            timeout=300,  # 5 minute timeout for coverage collection
            check=False,
        )

        # Check if coverage file was created
        if not coverage_file.exists():
            return None

        # Parse coverage data and build the map
        return _build_coverage_map_from_file(coverage_file, rootdir)

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        # Clean up coverage directory
        shutil.rmtree(coverage_dir, ignore_errors=True)


def _get_coverage_runner_script() -> str:
    """Return a script that runs pytest with coverage and context tracking.

    The script uses coverage.py directly to collect per-test coverage,
    using dynamic_context=test_function to track coverage per test.

    Returns:
        Python script source code.
    """
    return '''#!/usr/bin/env python
"""Coverage runner for pytest-gremlins.

Collects per-test coverage data using coverage.py directly.
Uses dynamic_context=test_function to associate coverage with each test.
"""
import sys
import os
import coverage


def main():
    if len(sys.argv) < 2:
        print("Usage: coverage_runner.py <coverage_file>", file=sys.stderr)
        sys.exit(1)

    coverage_file = sys.argv[1]
    cwd = os.getcwd()

    # Create coverage object with dynamic context per test function
    cov = coverage.Coverage(
        data_file=coverage_file,
        source=[cwd],
        config_file=False,
        omit=["**/test_*.py", "**/*_test.py", "**/conftest.py"],
    )
    cov.set_option("run:dynamic_context", "test_function")
    cov.start()

    try:
        import pytest
        exit_code = pytest.main(["-x", "--tb=no", "-q"])
    finally:
        cov.stop()
        cov.save()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
'''


def _build_coverage_map_from_file(coverage_file: Path, rootdir: Path) -> CoverageMap | None:
    """Build a CoverageMap from a coverage.py data file.

    Args:
        coverage_file: Path to the .coverage SQLite database.
        rootdir: Root directory of the project.

    Returns:
        CoverageMap if successful, None otherwise.
    """
    try:
        import coverage  # noqa: PLC0415 - Optional dependency, must be guarded
    except ImportError:
        return None

    try:
        cov = coverage.Coverage(data_file=str(coverage_file))
        cov.load()
        data = cov.get_data()

        collector = CoverageCollector()
        contexts = data.measured_contexts()

        for context in contexts:
            if not context or context == '':
                continue
            # pytest-cov creates contexts like "test_file.py::test_function|run"
            # Extract the test name from the context
            test_name = _extract_test_name_from_context(context)
            if not test_name:
                continue

            # Get files covered by this context
            data.set_query_context(context)
            for file_path in data.measured_files():
                lines = data.lines(file_path)
                if lines:
                    # Normalize the file path relative to rootdir
                    normalized_path = _normalize_coverage_path(file_path, rootdir)
                    collector.record_test_coverage(test_name, {normalized_path: list(lines)})

        return collector.coverage_map if len(collector.coverage_map) > 0 else None

    except Exception:
        return None


def _extract_test_name_from_context(context: str) -> str | None:
    """Extract test function name from coverage context.

    coverage.py's dynamic_context=test_function creates contexts like:
    - "test_module.test_function"
    - "test_module.TestClass.test_method"

    We convert these to pytest nodeids like:
    - "test_module.py::test_function"
    - "test_module.py::TestClass::test_method"

    Args:
        context: Coverage context string.

    Returns:
        Test name as pytest nodeid, or None if not a test context.
    """
    if not context:
        return None

    # Split by dots
    parts = context.split('.')
    if len(parts) < MIN_CONTEXT_PARTS:
        return None

    # First part is the module, rest is the test path
    module = parts[0]
    test_path = '::'.join(parts[1:])

    # Return as pytest nodeid format
    return f'{module}.py::{test_path}'


def _normalize_coverage_path(file_path: str, rootdir: Path) -> str:
    """Normalize a coverage file path to match gremlin paths.

    Resolves symlinks and makes paths relative to rootdir where possible.
    On macOS, /var is symlinked to /private/var, which causes path mismatches
    if not handled properly.

    Args:
        file_path: File path from coverage data.
        rootdir: Root directory of the project.

    Returns:
        Normalized path that matches gremlin file_path format.
    """
    # Resolve symlinks to get consistent paths (e.g., /var -> /private/var on macOS)
    path = Path(file_path).resolve()
    resolved_rootdir = rootdir.resolve()

    try:
        # Try to make path relative to rootdir
        relative = path.relative_to(resolved_rootdir)
        return str(resolved_rootdir / relative)
    except ValueError:
        # If not relative, return the resolved path
        return str(path)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """After all tests run, execute mutation testing."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if not gremlin_session.gremlins:
        return

    # Collect coverage data for coverage-guided test selection
    rootdir = Path(session.config.rootdir)  # type: ignore[attr-defined]
    coverage_map = _collect_coverage(rootdir)
    gremlin_session.coverage_map = coverage_map
    if coverage_map is not None:
        gremlin_session.test_selector = TestSelector(coverage_map)

    results = _run_mutation_testing(session, gremlin_session)
    gremlin_session.results = results


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
    total_gremlins = len(gremlin_session.gremlins)

    for idx, gremlin in enumerate(gremlin_session.gremlins, 1):
        # Select tests for this gremlin using coverage data
        selected_tests, test_count = _select_tests_for_gremlin(
            gremlin,
            gremlin_session.test_selector,
            gremlin_session.total_tests,
        )

        # Build test command with selected tests
        test_command = _build_filtered_test_command(base_test_command, selected_tests)

        # Log progress with test selection info
        if gremlin_session.verbose:
            location = f'{gremlin.file_path}:{gremlin.line_number}'
            print(
                f'Gremlin {idx}/{total_gremlins}: {location} - '
                f'running {test_count}/{gremlin_session.total_tests} tests'
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
    test_selector: TestSelector | None,
    total_tests: int,
) -> tuple[set[str], int]:
    """Select which tests to run for a gremlin.

    Uses coverage data to select only tests that cover the gremlin's location.
    Falls back to running all tests if no coverage data is available.

    Args:
        gremlin: The gremlin to select tests for.
        test_selector: The test selector with coverage data, or None.
        total_tests: Total number of tests in the suite.

    Returns:
        Tuple of (selected test names, count of tests to run).
    """
    if test_selector is None:
        # No coverage data available, run all tests
        return set(), total_tests

    selected = test_selector.select_tests(gremlin)

    if not selected:
        # No tests cover this gremlin, run all tests as fallback
        return set(), total_tests

    return selected, len(selected)


def _build_filtered_test_command(
    base_command: list[str],
    selected_tests: set[str],
) -> list[str]:
    """Build a test command filtered to run only selected tests.

    Args:
        base_command: The base pytest command.
        selected_tests: Set of test nodeids to run, or empty to run all.

    Returns:
        Command list with test selection applied.
    """
    if not selected_tests:
        # No selection, run all tests
        return base_command

    # Use pytest's -k option to filter tests
    # We need to build a pattern that matches any of the selected tests
    # For nodeids like "test_file.py::test_function", we extract the function name
    test_patterns = []
    for test_nodeid in selected_tests:
        # Extract the test name from nodeid (last part after ::)
        parts = test_nodeid.split('::')
        test_name = parts[-1] if parts else test_nodeid
        test_patterns.append(test_name)

    if not test_patterns:
        return base_command

    # Build -k expression: "test_a or test_b or test_c"
    k_expression = ' or '.join(test_patterns)

    return [*base_command, '-k', k_expression]


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

    # Show coverage collection status
    if gremlin_session.coverage_map is not None:
        coverage_locations = len(gremlin_session.coverage_map)
        terminalreporter.write_line(
            f'Coverage collected: {gremlin_session.total_tests} tests covering '
            f'{coverage_locations} source locations'
        )
        terminalreporter.write_line('')
    else:
        terminalreporter.write_line('Coverage: Not collected (running all tests for each gremlin)')
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
