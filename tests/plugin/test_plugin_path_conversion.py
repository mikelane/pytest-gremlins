"""Tests for module name to path conversion in plugin.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import _path_to_module_name


@pytest.mark.small
class DescribePathToModuleName:
    """Tests for _path_to_module_name function."""

    def it_flat_module_at_root(self):
        """Module at project root converts correctly."""
        rootdir = Path('/project')
        file_path = Path('/project/module.py')

        result = _path_to_module_name(file_path, rootdir)

        assert result == 'module'

    def it_package_module_at_root(self):
        """Module in package at project root converts correctly."""
        rootdir = Path('/project')
        file_path = Path('/project/mypackage/module.py')

        result = _path_to_module_name(file_path, rootdir)

        assert result == 'mypackage.module'

    def it_src_layout_module_excludes_src_prefix(self):
        """Module in src/ layout should NOT include 'src.' prefix.

        When using src/ layout, Python imports are like:
            from mypackage.module import func
        NOT:
            from src.mypackage.module import func

        The import hook must use the same module name as the import statement.
        """
        rootdir = Path('/project')
        file_path = Path('/project/src/mypackage/module.py')

        result = _path_to_module_name(file_path, rootdir)

        # This is the bug - currently returns 'src.mypackage.module'
        # but should return 'mypackage.module' to match import statements
        assert result == 'mypackage.module', (
            f"Expected 'mypackage.module' but got '{result}'. "
            "The 'src.' prefix should be stripped for src/ layout projects."
        )

    def it_resolves_nested_src_layout_module(self):
        """Deeply nested module in src/ layout converts correctly."""
        rootdir = Path('/project')
        file_path = Path('/project/src/mypackage/subpackage/module.py')

        result = _path_to_module_name(file_path, rootdir)

        assert result == 'mypackage.subpackage.module'

    @pytest.mark.parametrize(
        ('relative_path', 'expected'),
        [
            ('pkg/__init__.py', 'pkg'),
            ('pkg/sub/__init__.py', 'pkg.sub'),
            ('src/pkg/__init__.py', 'pkg'),
            ('src/pkg/sub/__init__.py', 'pkg.sub'),
        ],
    )
    def it_names_a_package_init_after_its_package(self, relative_path: str, expected: str) -> None:
        rootdir = Path('/project')

        result = _path_to_module_name(rootdir / relative_path, rootdir)

        assert result == expected

    @pytest.mark.parametrize('relative_path', ['__init__.py', 'src/__init__.py'])
    def it_keeps_the_literal_name_for_an_init_that_belongs_to_no_package(self, relative_path: str) -> None:
        rootdir = Path('/project')

        result = _path_to_module_name(rootdir / relative_path, rootdir)

        assert result == '__init__'
