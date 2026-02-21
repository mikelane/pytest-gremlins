"""Tests for subprocess coverage support via sitecustomize.py.

When COVERAGE_PROCESS_START is set and sitecustomize.py is on PYTHONPATH,
every subprocess Python instance calls coverage.process_startup() and writes
its own .coverage.* data file, which gets combined by the parent process.

Reference: https://coverage.readthedocs.io/en/latest/subprocess.html
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.small
class TestSitecustomizeExists:
    """Verify sitecustomize.py is present at the project root."""

    def test_sitecustomize_exists_at_project_root(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        sitecustomize = project_root / 'sitecustomize.py'
        assert sitecustomize.exists(), (
            'sitecustomize.py must exist at the project root so that '
            'PYTHONPATH=. makes it importable by subprocess Python instances'
        )

    def test_sitecustomize_is_valid_python(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        source = (project_root / 'sitecustomize.py').read_text(encoding='utf-8')
        # ast.parse raises SyntaxError if the file is not valid Python
        ast.parse(source)

    def test_sitecustomize_calls_coverage_process_startup(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        source = (project_root / 'sitecustomize.py').read_text(encoding='utf-8')
        tree = ast.parse(source)

        # Find any call to coverage.process_startup()
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'process_startup'
        ]
        assert calls, 'sitecustomize.py must call coverage.process_startup()'

    def test_sitecustomize_imports_coverage(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        source = (project_root / 'sitecustomize.py').read_text(encoding='utf-8')
        tree = ast.parse(source)

        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and any(alias.name == 'coverage' for alias in node.names)
        ]
        assert imports, 'sitecustomize.py must import coverage'


@pytest.mark.small
class TestCoverageRunConfig:
    """Verify pyproject.toml coverage config enables parallel subprocess tracking."""

    def test_coverage_run_parallel_is_true(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        pyproject = project_root / 'pyproject.toml'
        content = pyproject.read_text(encoding='utf-8')
        # parallel = true is needed so each subprocess writes its own .coverage.<pid> file
        assert 'parallel = true' in content, (
            '[tool.coverage.run] must have parallel = true for subprocess coverage to work'
        )

    def test_coverage_run_has_source_configured(self) -> None:
        project_root = Path(__file__).parent.parent.parent
        pyproject = project_root / 'pyproject.toml'
        content = pyproject.read_text(encoding='utf-8')
        assert 'source = ["src/pytest_gremlins"]' in content, (
            '[tool.coverage.run] must declare source so COVERAGE_PROCESS_START '
            'knows which files to track in subprocesses'
        )


@pytest.mark.small
class TestSubprocessCoverageIntegration:
    """Verify subprocess Python instances write coverage data when env vars are set."""

    def test_subprocess_writes_coverage_file_when_env_vars_set(self, tmp_path: Path) -> None:
        project_root = Path(__file__).parent.parent.parent

        # Write a trivial Python module that subprocess will import and run
        target = tmp_path / 'target.py'
        target.write_text('def add(a, b):\n    return a + b\n\nresult = add(1, 2)\n')

        env = os.environ.copy()
        env['COVERAGE_PROCESS_START'] = str(project_root / 'pyproject.toml')
        env['PYTHONPATH'] = str(project_root)

        result = subprocess.run(
            [sys.executable, str(target)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            check=False,
        )

        assert result.returncode == 0, f'Subprocess failed: {result.stderr}'

        coverage_files = list(tmp_path.glob('.coverage*'))
        assert coverage_files, (
            'Subprocess must write a .coverage.* file when COVERAGE_PROCESS_START and PYTHONPATH are set'
        )
