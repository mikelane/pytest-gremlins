"""Tests for pytest node ID normalization in plugin.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins import plugin


@pytest.mark.small
class TestMakeNodeIdsRelative:
    """Tests for _make_node_ids_relative function.

    pytest node IDs have the format: path/to/file.py::test_function
    This function converts absolute paths to relative paths and strips
    plugin-added decorations.
    """

    def test_relative_node_id_unchanged(self):
        """A relative node ID passes through unchanged."""
        rootdir = Path('/project')
        node_ids = ['tests/test_example.py::test_something']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py::test_something']

    def test_absolute_path_made_relative(self):
        """An absolute path node ID is made relative to rootdir."""
        rootdir = Path('/project')
        node_ids = ['/project/tests/test_example.py::test_something']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py::test_something']

    def test_absolute_path_without_separator_made_relative(self):
        """An absolute path without :: is made relative."""
        rootdir = Path('/project')
        node_ids = ['/project/tests/test_example.py']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py']

    def test_plugin_suffix_stripped(self):
        """Plugin-added suffixes like [SMALL] are stripped.

        pytest-test-categories and similar plugins add display-only
        decorations to node IDs. These must be stripped because they
        are not part of the actual node ID that pytest accepts.
        """
        rootdir = Path('/project')
        node_ids = ['tests/test_example.py::test_something [SMALL]']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py::test_something']

    def test_plugin_suffix_stripped_with_absolute_path(self):
        """Plugin suffix stripped AND absolute path made relative."""
        rootdir = Path('/project')
        node_ids = ['/project/tests/test_example.py::test_something [MEDIUM]']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py::test_something']

    def test_multiple_node_ids_processed(self):
        """Multiple node IDs are all processed correctly."""
        rootdir = Path('/project')
        node_ids = [
            'tests/test_a.py::test_one',
            '/project/tests/test_b.py::test_two [SMALL]',
            '/project/tests/test_c.py::test_three',
        ]

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == [
            'tests/test_a.py::test_one',
            'tests/test_b.py::test_two',
            'tests/test_c.py::test_three',
        ]

    def test_path_outside_rootdir_unchanged(self):
        """Paths outside rootdir are left unchanged (minus suffix)."""
        rootdir = Path('/project')
        node_ids = ['/other/tests/test_example.py::test_something']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        # Path doesn't start with rootdir, so it stays as-is
        assert result == ['/other/tests/test_example.py::test_something']

    def test_empty_list_returns_empty(self):
        """Empty list returns empty list."""
        rootdir = Path('/project')
        node_ids: list[str] = []

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == []

    def test_large_suffix_stripped(self):
        """LARGE suffix is stripped."""
        rootdir = Path('/project')
        node_ids = ['tests/test_example.py::test_something [LARGE]']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_example.py::test_something']

    def test_suffix_case_sensitive(self):
        """Suffix stripping is case-sensitive (uppercase only)."""
        rootdir = Path('/project')
        # Lowercase [small] should NOT be stripped - only [SMALL]
        node_ids = ['tests/test_example.py::test_something [small]']

        result = plugin._make_node_ids_relative(node_ids, rootdir)

        # lowercase [small] is not stripped - only uppercase
        assert result == ['tests/test_example.py::test_something [small]']
