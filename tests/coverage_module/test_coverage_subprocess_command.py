"""Tests for _run_tests_with_coverage subprocess command construction.

Verifies that the coverage subprocess uses the subprocess_bootstrap plugin
for full node ID contexts instead of dynamic_context=test_function.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_coverage,
    _run_tests_with_coverage,
)


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

    def it_uses_source_dot_when_no_coverage_include(self, tmp_path: Path) -> None:
        """Without coverage_include, the coveragerc keeps the source = . default."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert captured_content
        assert 'source = .' in captured_content[0]
        assert 'include =' not in captured_content[0]

    def it_writes_include_section_when_coverage_include_provided(self, tmp_path: Path) -> None:
        """With coverage_include, the coveragerc lists those paths under include and drops source = ."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        include = ['/abs/src/foo.py', '/abs/src/bar.py']
        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path, coverage_include=include)

        assert captured_content
        content = captured_content[0]
        assert 'source = .' not in content
        assert 'include =' in content
        assert '/abs/src/foo.py' in content
        assert '/abs/src/bar.py' in content


@pytest.mark.medium
class DescribeCollectCoverageScoping:
    """_collect_coverage scopes coverage to the gremlin source files."""

    def it_passes_resolved_gremlin_source_files_as_coverage_include(self, tmp_path: Path) -> None:
        """_collect_coverage forwards the resolved, sorted gremlin file paths as coverage_include."""
        source_file = tmp_path / 'mymodule.py'
        source_file.write_text('x = 1\n')

        gremlin_a = MagicMock(spec=['file_path'])
        gremlin_a.file_path = str(source_file)
        gremlin_b = MagicMock(spec=['file_path'])
        gremlin_b.file_path = str(source_file)

        gs = GremlinSession(enabled=True)
        gs.gremlins = [gremlin_a, gremlin_b]

        captured: dict[str, object] = {}

        def fake_run(*_args: object, **kwargs: object) -> dict[str, dict[str, list[int]]]:
            captured.update(kwargs)
            return {'tests/test_x.py::test_x': {str(source_file): [1]}}

        with patch('pytest_gremlins.plugin._run_tests_with_coverage', side_effect=fake_run):
            _collect_coverage(gs, tmp_path)

        assert captured['coverage_include'] == [str(source_file.resolve())]
