"""Tests for _run_tests_with_coverage subprocess command construction.

Verifies that the coverage subprocess uses the subprocess_bootstrap plugin
for full node ID contexts instead of dynamic_context=test_function.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage


@pytest.mark.medium
class DescribeRunTestsWithCoverageCommand:
    """Tests for subprocess command construction in _run_tests_with_coverage."""

    def it_includes_subprocess_bootstrap_plugin(self, tmp_path: Path) -> None:
        """The subprocess command loads the bootstrap plugin via -p."""
        captured_cmd: list[str] = []

        def capture_cmd(*args: object, **_kwargs: object) -> None:
            captured_cmd.extend(args[0])  # type: ignore[index]

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert '-p' in captured_cmd
        bootstrap_idx = captured_cmd.index('-p')
        assert captured_cmd[bootstrap_idx + 1] == 'pytest_gremlins.coverage.subprocess_bootstrap'

    def it_disables_gremlins_plugin_in_subprocess(self, tmp_path: Path) -> None:
        """The subprocess command disables the full gremlins plugin via -p no:gremlins."""
        captured_cmd: list[str] = []

        def capture_cmd(*args: object, **_kwargs: object) -> None:
            captured_cmd.extend(args[0])  # type: ignore[index]

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        p_indices = [i for i, v in enumerate(captured_cmd) if v == '-p']
        no_gremlins_found = any(captured_cmd[i + 1] == 'no:gremlins' for i in p_indices)
        assert no_gremlins_found, f'-p no:gremlins not found in command: {captured_cmd}'

    def it_does_not_use_dynamic_context_in_coveragerc(self, tmp_path: Path) -> None:
        """The generated coveragerc does not contain dynamic_context = test_function."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert captured_content, 'coveragerc was not written before subprocess.run'
        assert 'dynamic_context' not in captured_content[0]
