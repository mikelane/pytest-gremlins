"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.instrumentation.transformer import get_default_registry, transform_source
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


if TYPE_CHECKING:
    import pytest

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.operators import GremlinOperator


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
    """

    enabled: bool = False
    operators: list[GremlinOperator] = field(default_factory=list)
    report_format: str = 'console'
    gremlins: list[Gremlin] = field(default_factory=list)
    results: list[GremlinResult] = field(default_factory=list)
    source_files: dict[str, str] = field(default_factory=dict)
    test_files: list[Path] = field(default_factory=list)
    target_paths: list[Path] = field(default_factory=list)


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

    source_files = _discover_source_files(session, gremlin_session)
    gremlin_session.source_files = source_files

    all_gremlins: list[Gremlin] = []
    for file_path, source in source_files.items():
        gremlins, _ = transform_source(source, file_path, gremlin_session.operators)
        all_gremlins.extend(gremlins)

    gremlin_session.gremlins = all_gremlins


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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """After all tests run, execute mutation testing."""
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return

    if not gremlin_session.gremlins:
        return

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
    test_command = _build_test_command()

    for gremlin in gremlin_session.gremlins:
        result = _test_gremlin(gremlin, test_command, rootdir)
        results.append(result)

    return results


def _build_test_command() -> list[str]:
    """Build the command to run tests.

    Returns:
        Command list to run tests.
    """
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
) -> GremlinResult:
    """Test a single gremlin by running tests with the mutation active.

    Args:
        gremlin: The gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory of the project.

    Returns:
        Result of testing the gremlin.
    """
    env = os.environ.copy()
    env[ACTIVE_GREMLIN_ENV_VAR] = gremlin.gremlin_id

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
    _set_session(None)
