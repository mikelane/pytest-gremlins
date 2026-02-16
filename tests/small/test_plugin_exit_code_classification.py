"""Tests for subprocess exit code classification when testing gremlins.

Issue #93: import/collection errors were being counted as "zapped".
"""

from __future__ import annotations

import ast
import subprocess
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import _test_gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus


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


@pytest.mark.small
class TestTestGremlinExitCodeClassification:
    """Tests for _test_gremlin exit code handling."""

    def test_exit_code_0_is_survived(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_gremlin: Gremlin
    ) -> None:
        """Exit code 0 means all tests passed (mutation not caught) -> SURVIVED."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=0, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.SURVIVED

    def test_exit_code_1_is_zapped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_gremlin: Gremlin
    ) -> None:
        """Exit code 1 means tests failed (mutation caught) -> ZAPPED."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=1, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ZAPPED

    @pytest.mark.parametrize(
        'exit_code',
        [
            pytest.param(2, id='interrupted'),
            pytest.param(3, id='internal-error'),
            pytest.param(4, id='usage-error'),
            pytest.param(5, id='no-tests-collected'),
        ],
    )
    def test_non_test_exit_codes_are_error(
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

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ERROR
