"""Tests for plugin helper functions.

These tests cover the utility functions in plugin.py that can be tested in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import (
    _add_source_file,
    _build_test_command,
    _make_node_ids_relative,
    _path_to_module_name,
    _should_include_file,
)


@pytest.mark.small
class TestShouldIncludeFile:
    """Tests for _should_include_file function."""

    def test_excludes_test_files_with_test_prefix(self, tmp_path: Path) -> None:
        """Files starting with test_ are excluded."""
        test_file = tmp_path / 'test_something.py'
        test_file.touch()
        assert _should_include_file(test_file) is False

    def test_excludes_test_files_with_test_suffix(self, tmp_path: Path) -> None:
        """Files ending with _test.py are excluded."""
        test_file = tmp_path / 'something_test.py'
        test_file.touch()
        assert _should_include_file(test_file) is False

    def test_excludes_conftest(self, tmp_path: Path) -> None:
        """conftest.py files are excluded."""
        conftest = tmp_path / 'conftest.py'
        conftest.touch()
        assert _should_include_file(conftest) is False

    def test_excludes_pycache_files(self, tmp_path: Path) -> None:
        """Files in __pycache__ are excluded."""
        pycache = tmp_path / '__pycache__'
        pycache.mkdir()
        cached_file = pycache / 'module.cpython-311.pyc'
        cached_file.touch()
        # The path contains __pycache__
        assert _should_include_file(cached_file) is False

    def test_includes_regular_source_files(self, tmp_path: Path) -> None:
        """Regular source files are included."""
        source_file = tmp_path / 'module.py'
        source_file.touch()
        assert _should_include_file(source_file) is True


@pytest.mark.small
class TestAddSourceFile:
    """Tests for _add_source_file function."""

    def test_adds_valid_python_file(self, tmp_path: Path) -> None:
        """Valid Python file is added to the collection."""
        source_file = tmp_path / 'module.py'
        source_file.write_text('x = 1\n')
        source_files: dict[str, str] = {}

        _add_source_file(source_file, source_files)

        assert str(source_file) in source_files
        assert source_files[str(source_file)] == 'x = 1\n'

    def test_skips_file_with_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error is silently skipped."""
        bad_file = tmp_path / 'bad.py'
        bad_file.write_text('def broken(\n')  # Syntax error
        source_files: dict[str, str] = {}

        _add_source_file(bad_file, source_files)

        assert str(bad_file) not in source_files

    def test_skips_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file is silently skipped."""
        missing_file = tmp_path / 'missing.py'
        source_files: dict[str, str] = {}

        _add_source_file(missing_file, source_files)

        assert str(missing_file) not in source_files


@pytest.mark.small
class TestMakeNodeIdsRelative:
    """Tests for _make_node_ids_relative function."""

    def test_makes_absolute_paths_relative(self, tmp_path: Path) -> None:
        """Absolute paths in node IDs are made relative to rootdir."""
        rootdir = tmp_path
        node_ids = [f'{tmp_path}/tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_keeps_relative_paths_unchanged(self, tmp_path: Path) -> None:
        """Relative paths in node IDs are unchanged."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_strips_test_category_suffix(self, tmp_path: Path) -> None:
        """Plugin-added suffixes like [SMALL] are stripped."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func [SMALL]']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_handles_node_id_without_double_colon(self, tmp_path: Path) -> None:
        """Handles node IDs that are just file paths (no ::)."""
        rootdir = tmp_path
        abs_path = tmp_path / 'tests' / 'test_module.py'
        node_ids = [str(abs_path)]

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def test_handles_relative_path_without_double_colon(self, tmp_path: Path) -> None:
        """Handles relative paths without ::."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def test_handles_non_relative_absolute_path(self, tmp_path: Path) -> None:
        """Handles absolute paths that are not under rootdir."""
        rootdir = tmp_path
        node_ids = ['/some/other/path/test.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['/some/other/path/test.py::test_func']


@pytest.mark.small
class TestPathToModuleName:
    """Tests for _path_to_module_name function."""

    def test_converts_relative_path_to_module(self, tmp_path: Path) -> None:
        """Converts relative path to module name."""
        file_path = tmp_path / 'package' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'package.module'

    def test_strips_src_prefix(self, tmp_path: Path) -> None:
        """Strips src/ prefix from path since it's a layout convention."""
        file_path = tmp_path / 'src' / 'mypackage' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'mypackage.module'

    def test_file_not_relative_to_rootdir(self, tmp_path: Path) -> None:
        """When file is not under rootdir, uses just the filename.

        Covers lines 426-427: ValueError catch for relative_to.
        """
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        file_path = Path('/some/other/path/module.py')

        result = _path_to_module_name(file_path, rootdir)

        # Just returns the filename without .py extension
        assert result == 'module'


@pytest.mark.small
class TestBuildTestCommand:
    """Tests for _build_test_command function."""

    def test_with_instrumented_dir(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, uses bootstrap script."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert 'gremlin_bootstrap.py' in result[1]
        assert '-x' in result
        assert '--tb=no' in result

    def test_without_instrumented_dir(self) -> None:
        """When instrumented_dir is None, runs pytest directly.

        Covers line 1321: return branch when instrumented_dir is None.
        """
        result = _build_test_command(None)

        assert '-m' in result
        assert 'pytest' in result
        assert '-x' in result
        assert '--tb=no' in result
