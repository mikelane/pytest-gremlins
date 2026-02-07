"""Tests for subprocess exit code classification when testing gremlins.

Issue #93: import/collection errors were being counted as "zapped".
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import _test_gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus


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

    def test_exit_code_1_is_zapped(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_gremlin: Gremlin) -> None:
        """Exit code 1 means tests failed (mutation caught) -> ZAPPED."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=1, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ZAPPED

    def test_exit_code_2_is_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_gremlin: Gremlin) -> None:
        """Exit code 2 indicates pytest errors (collection/import/etc) -> ERROR."""

        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args=['pytest'], returncode=2, stdout=b'', stderr=b'')

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ERROR
