"""The bootstrap's "suite failed to load" exit code maps to ZAPPED at every call site (issue #550)."""

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
from pytest_gremlins.parallel.exit_codes import (
    COLLECTION_KILLING_TEST,
    GREMLIN_COLLECTION_FAILED_EXIT_CODE,
)
from pytest_gremlins.plugin import _test_gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus

EXIT_COLLECTION_FAILED = [
    sys.executable,
    '-c',
    f'import sys; sys.exit({GREMLIN_COLLECTION_FAILED_EXIT_CODE})',
]
EXIT_USAGE_ERROR = [sys.executable, '-c', 'import sys; sys.exit(4)']


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
class DescribeCollectionFailedExitCode:
    def it_is_distinct_from_pytests_own_exit_codes_and_the_runner_abstention(self) -> None:
        assert GREMLIN_COLLECTION_FAILED_EXIT_CODE not in {0, 1, 2, 3, 4, 5, 70}

    def it_names_the_killing_test_after_the_collection_phase(self) -> None:
        assert COLLECTION_KILLING_TEST == '<collection>'


@pytest.mark.medium
class DescribeCollectionFailedMapping:
    """ZAPPED with the collection killing test, at all subprocess call sites."""

    def it_maps_to_zapped_in_the_sequential_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=['x'], returncode=GREMLIN_COLLECTION_FAILED_EXIT_CODE, stdout=b'', stderr=b''
            )

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert (result.status, result.killing_test) == (GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST)

    def it_maps_to_zapped_in_the_parallel_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        result = pool._run_gremlin_test('g001', EXIT_COLLECTION_FAILED, str(tmp_path), {}, timeout=30)

        assert (result.status, result.killing_test) == (GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST)

    def it_maps_to_zapped_in_the_persistent_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        result = persistent_pool._run_gremlin_test('g001', EXIT_COLLECTION_FAILED, str(tmp_path), {}, timeout=30)

        assert (result.status, result.killing_test) == (GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST)

    def it_maps_to_zapped_in_the_persistent_pool_batch_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        results = persistent_pool._run_gremlin_batch(
            ['g001', 'g002'], EXIT_COLLECTION_FAILED, str(tmp_path), {}, timeout=30
        )

        assert [(r.status, r.killing_test) for r in results] == [
            (GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST)
        ] * 2


@pytest.mark.medium
class DescribeUsageErrorsStayErrors:
    """pytest's own usage-error exit code (4) is still our bug, never a kill."""

    def it_keeps_exit_4_as_error_in_the_sequential_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['x'], returncode=4, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ERROR

    def it_keeps_exit_4_as_error_in_the_parallel_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        result = pool._run_gremlin_test('g001', EXIT_USAGE_ERROR, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR

    def it_keeps_exit_4_as_error_in_the_persistent_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        result = persistent_pool._run_gremlin_test('g001', EXIT_USAGE_ERROR, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
