"""Tests for subprocess exit code classification when testing gremlins.

Issue #93: import/collection errors were being counted as "zapped".
"""

from __future__ import annotations

import ast
import subprocess
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.verdicts import (
    _test_gremlin,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sample_gremlin() -> Gremlin:
    """Create a sample gremlin for testing."""
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=42,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


@pytest.mark.medium
class DescribeGremlinExitCodeClassification:
    """Tests for _test_gremlin exit code handling."""

    def it_maps_exit_code_0_to_survived(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        """Exit code 0 means all tests passed (mutation not caught) -> SURVIVED."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=0, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None, timeout=30)

        assert result.status == GremlinResultStatus.SURVIVED

    def it_maps_exit_code_1_to_zapped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        """Exit code 1 means tests failed (mutation caught) -> ZAPPED."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=1, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None, timeout=30)

        assert result.status == GremlinResultStatus.ZAPPED

    @pytest.mark.parametrize('returncode', [0, 1])
    def it_records_the_elapsed_time_of_the_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
        returncode: int,
    ) -> None:
        """The cache reuses a verdict at another timeout only when it knows how long the run took (#567)."""
        clock = iter([100.0, 102.5])

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=returncode, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)
        monkeypatch.setattr('pytest_gremlins.verdicts.time.monotonic', lambda: next(clock))

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None, timeout=30)

        assert result.execution_time_ms == 2500.0

    @pytest.mark.parametrize(
        'exit_code',
        [
            pytest.param(2, id='interrupted'),
            pytest.param(3, id='internal-error'),
            pytest.param(4, id='usage-error'),
            pytest.param(5, id='no-tests-collected'),
        ],
    )
    def it_classifies_non_test_exit_codes_as_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
        exit_code: int,
    ) -> None:
        """Exit codes 2-5 indicate non-test failures -> ERROR."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=exit_code, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
