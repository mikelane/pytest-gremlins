"""Tests for mapping mutant-induced collection and import errors to ZAPPED (<collection>).

Acceptance criteria for issue #550:
- Mutants breaking conftest imports, test-module imports, or parametrize IDs are ZAPPED
  with killing test '<collection>' in sequential, parallel, and batch modes.
- Per-gremlin usage errors caused by bad arguments remain ERROR.
- Classification uses a deterministic signal from the bootstrap (exit 71) where possible,
  falling back to stderr/stdout inspection.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel import (
    persistent_pool,
    pool,
)
from pytest_gremlins.parallel.lightweight import (
    BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE,
    COLLECTION_KILLING_TEST,
    is_collection_failure,
)
from pytest_gremlins.plugin import _test_gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus


@pytest.fixture
def sample_gremlin() -> Gremlin:
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=42,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


@pytest.mark.small
class DescribeIsCollectionFailure:
    """Helper determines whether a test outcome was a mutant-caused collection failure."""

    def it_recognizes_bootstrap_exit_code(self) -> None:
        assert is_collection_failure(BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE) is True

    def it_recognizes_conftest_import_failure_from_stderr(self) -> None:
        stderr = (
            b"ImportError while loading conftest '/path/to/conftest.py'\nModuleNotFoundError: No module named 'attr'"
        )
        assert is_collection_failure(4, stderr=stderr) is True

    def it_recognizes_module_collection_error_from_stdout(self) -> None:
        stdout = b'ERROR collecting tests/test_foo.py\nERROR: found no collectors for tests/test_foo.py::test_bar'
        assert is_collection_failure(4, stdout=stdout) is True

    def it_recognizes_not_found_parametrize_id_from_stdout(self) -> None:
        stdout = b'ERROR: not found: tests/test_foo.py::test_bar[param1]\n(no match in any of [<Module test_foo.py>])'
        assert is_collection_failure(4, stdout=stdout) is True

    def it_rejects_unrecognized_arguments_usage_error(self) -> None:
        stderr = b'pytest: error: unrecognized arguments: --invalid-flag\n'
        assert is_collection_failure(4, stderr=stderr) is False

    def it_rejects_file_or_directory_not_found_usage_error(self) -> None:
        stderr = b'ERROR: file or directory not found: nonexistent.py\n'
        assert is_collection_failure(4, stderr=stderr) is False

    def it_rejects_internal_errors(self) -> None:
        stderr = b'INTERNALERROR> Traceback...\n'
        assert is_collection_failure(3, stderr=stderr) is False

    def it_rejects_zero_and_one_exit_codes(self) -> None:
        assert is_collection_failure(0) is False
        assert is_collection_failure(1) is False


@pytest.mark.medium
class DescribeCollectionFailureMapping:
    """Mutant-broken collection maps to ZAPPED (<collection>) across all executors."""

    def it_maps_to_zapped_collection_in_the_sequential_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=['pytest'],
                returncode=BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE,
                stdout=b'',
                stderr=b'collection failed',
            )

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ZAPPED
        assert result.killing_test == COLLECTION_KILLING_TEST

    def it_maps_to_zapped_collection_in_the_parallel_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        cmd = [sys.executable, '-c', f'import sys; sys.exit({BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE})']
        result = pool._run_gremlin_test('g001', cmd, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ZAPPED
        assert result.killing_test == COLLECTION_KILLING_TEST

    def it_maps_to_zapped_collection_in_the_persistent_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        cmd = [sys.executable, '-c', f'import sys; sys.exit({BOOTSTRAP_COLLECTION_FAILED_EXIT_CODE})']
        result = persistent_pool._run_gremlin_test('g001', cmd, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ZAPPED
        assert result.killing_test == COLLECTION_KILLING_TEST

    def it_preserves_error_for_bad_arguments_in_the_sequential_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=['pytest'],
                returncode=4,
                stdout=b'',
                stderr=b'pytest: error: unrecognized arguments: --bogus-arg',
            )

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ERROR
        assert 'unrecognized arguments' in (result.error_output or '')

    def it_preserves_error_for_bad_arguments_in_the_parallel_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        cmd = [
            sys.executable,
            '-c',
            'import sys; sys.stderr.write("pytest: error: unrecognized arguments: --bogus\\n"); sys.exit(4)',
        ]
        result = pool._run_gremlin_test('g001', cmd, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert 'unrecognized arguments' in (result.error_output or '')

    def it_preserves_error_for_bad_arguments_in_the_persistent_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        cmd = [
            sys.executable,
            '-c',
            'import sys; sys.stderr.write("pytest: error: unrecognized arguments: --bogus\\n"); sys.exit(4)',
        ]
        result = persistent_pool._run_gremlin_test('g001', cmd, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert 'unrecognized arguments' in (result.error_output or '')
