"""Tests for pytest-cov conflict prevention in coverage subprocess.

Verifies that pytest-gremlins clears user-configured addopts when running
the coverage subprocess, preventing pytest-cov from hijacking coverage
collection. Also verifies a warning is emitted when coverage returns
empty data.

See: https://github.com/mikelane/pytest-gremlins/issues/113
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch
import warnings

import pytest

from pytest_gremlins.plugin import GremlinSession, _collect_coverage, _run_tests_with_coverage


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestCoverageSubprocessClearsAddopts:
    """Verify the coverage subprocess includes -o addopts= to clear user config."""

    def test_coverage_subprocess_command_includes_addopts_override(self, tmp_path: Path) -> None:
        """The subprocess command clears pytest addopts to prevent pytest-cov interference."""
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(['tests/test_example.py::test_one'], tmp_path)

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert '-o' in cmd
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts='

    def test_addopts_override_appears_before_test_node_ids(self, tmp_path: Path) -> None:
        """The -o addopts= flag appears before the test node IDs in the command."""
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(
                ['tests/test_a.py::test_one', 'tests/test_b.py::test_two'],
                tmp_path,
            )

        cmd = captured_cmd[0]
        addopts_idx = cmd.index('-o')
        test_id_positions = [cmd.index(tid) for tid in ['tests/test_a.py::test_one', 'tests/test_b.py::test_two']]
        for pos in test_id_positions:
            assert addopts_idx < pos


@pytest.mark.small
class TestEmptyCoverageWarning:
    """Verify a warning is emitted when coverage collection returns empty data."""

    def test_warns_when_coverage_data_is_empty(self, tmp_path: Path) -> None:
        """A warning fires when _run_tests_with_coverage returns an empty dict."""
        session = GremlinSession(
            enabled=True,
            gremlins=[],
            test_node_ids={},
        )

        with (
            patch(
                'pytest_gremlins.plugin._run_tests_with_coverage',
                return_value={},
            ),
            pytest.warns(
                UserWarning,
                match='Coverage collection returned no data',
            ),
        ):
            _collect_coverage(session, tmp_path)

    def test_no_warning_when_coverage_data_is_present(self, tmp_path: Path) -> None:
        """No warning fires when coverage data contains entries."""
        session = GremlinSession(
            enabled=True,
            gremlins=[],
            test_node_ids={},
        )

        coverage_data = {
            'test_func': {
                'src/module.py': [1, 2, 3],
            },
        }

        with (
            patch(
                'pytest_gremlins.plugin._run_tests_with_coverage',
                return_value=coverage_data,
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            _collect_coverage(session, tmp_path)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0
