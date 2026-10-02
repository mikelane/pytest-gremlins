"""Tests for bootstrap script collection failure detection.

Issue #550: mutants breaking conftest import, test module import, or parametrized test IDs
cause the bootstrap script to exit with BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE (71), while
usage errors (bad CLI flags) exit with 4.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.parallel.lightweight import BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE
from pytest_gremlins.plugin import _get_bootstrap_script


def _run_bootstrap(bootstrap_path: Path, sources_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(bootstrap_path), *args],
        env={'PYTEST_GREMLINS_SOURCES_FILE': str(sources_path), 'PATH': sys.path[0]},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.medium
class DescribeBootstrapCollectionFailureDetection:
    """Bootstrap script classifies collection/import errors vs CLI usage errors."""

    @pytest.fixture
    def setup_env(self, tmp_path: Path) -> tuple[Path, Path]:
        bootstrap_script = tmp_path / 'gremlin_bootstrap.py'
        bootstrap_script.write_text(_get_bootstrap_script(), encoding='utf-8')

        sources_file = tmp_path / 'sources.json'
        sources_file.write_text(json.dumps({}), encoding='utf-8')
        return bootstrap_script, sources_file

    def it_exits_with_71_when_conftest_import_fails(
        self,
        tmp_path: Path,
        setup_env: tuple[Path, Path],
    ) -> None:
        bootstrap_script, sources_file = setup_env
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('raise ImportError("attr broken by mutant")\n', encoding='utf-8')

        res = _run_bootstrap(bootstrap_script, sources_file, ['-x', '-q', str(tmp_path)])
        assert res.returncode == BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE

    def it_exits_with_71_when_test_module_import_fails(
        self,
        tmp_path: Path,
        setup_env: tuple[Path, Path],
    ) -> None:
        bootstrap_script, sources_file = setup_env
        test_file = tmp_path / 'test_broken.py'
        test_file.write_text('raise ImportError("test module import failed")\n', encoding='utf-8')

        res = _run_bootstrap(bootstrap_script, sources_file, ['-x', '-q', f'{test_file}::test_target'])
        assert res.returncode == BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE

    def it_exits_with_71_when_parametrized_test_id_not_found(
        self,
        tmp_path: Path,
        setup_env: tuple[Path, Path],
    ) -> None:
        bootstrap_script, sources_file = setup_env
        test_file = tmp_path / 'test_ok.py'
        test_file.write_text('def test_good(): pass\n', encoding='utf-8')

        res = _run_bootstrap(bootstrap_script, sources_file, ['-x', '-q', f'{test_file}::test_missing_id'])
        assert res.returncode == BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE

    def it_preserves_exit_code_4_for_unrecognized_argument(
        self,
        tmp_path: Path,
        setup_env: tuple[Path, Path],
    ) -> None:
        bootstrap_script, sources_file = setup_env
        test_file = tmp_path / 'test_ok.py'
        test_file.write_text('def test_good(): pass\n', encoding='utf-8')

        res = _run_bootstrap(bootstrap_script, sources_file, ['--nonexistent-argument-xyz-123', str(test_file)])
        assert res.returncode == 4
