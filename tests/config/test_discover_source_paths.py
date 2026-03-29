"""Tests for auto-discovery of source paths from pyproject.toml packaging metadata.

When [tool.pytest-gremlins].paths is not configured, the plugin reads
setuptools packaging metadata to find source directories.
"""

from pathlib import Path

import pytest

from pytest_gremlins.config import discover_source_paths


@pytest.mark.medium
class DescribeDiscoverSourcePaths:
    """Tests for discover_source_paths function."""

    def it_returns_empty_list_when_no_pyproject_toml(self, tmp_path):
        """Returns empty list when pyproject.toml does not exist."""
        result = discover_source_paths(tmp_path)

        assert result == []

    def it_returns_empty_list_when_no_setuptools_section(self, tmp_path):
        """Returns empty list when no [tool.setuptools] section exists."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myproject"\n')

        result = discover_source_paths(tmp_path)

        assert result == []

    def it_discovers_setuptools_packages(self, tmp_path):
        """Reads [tool.setuptools].packages list."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp"]\n')
        (tmp_path / 'cogapp').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('cogapp')]

    def it_discovers_multiple_setuptools_packages(self, tmp_path):
        """Reads multiple packages from [tool.setuptools].packages."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["pkg_a", "pkg_b"]\n')
        (tmp_path / 'pkg_a').mkdir()
        (tmp_path / 'pkg_b').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('pkg_a'), Path('pkg_b')]

    def it_discovers_setuptools_package_dir(self, tmp_path):
        """Reads [tool.setuptools].package-dir mapping."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.package-dir]\n"" = "lib"\n')
        (tmp_path / 'lib').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('lib')]

    def it_discovers_setuptools_packages_find_where(self, tmp_path):
        """Reads [tool.setuptools.packages.find].where list."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.packages.find]\nwhere = ["lib"]\n')
        (tmp_path / 'lib').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('lib')]

    def it_discovers_multiple_find_where_dirs(self, tmp_path):
        """Reads multiple directories from packages.find.where."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.packages.find]\nwhere = ["lib", "ext"]\n')
        (tmp_path / 'lib').mkdir()
        (tmp_path / 'ext').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('lib'), Path('ext')]

    def it_filters_nonexistent_packages(self, tmp_path):
        """Only returns packages whose directories actually exist on disk."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["exists", "missing"]\n')
        (tmp_path / 'exists').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('exists')]

    def it_filters_nonexistent_package_dir(self, tmp_path):
        """Only returns package-dir values whose directories exist."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.package-dir]\n"" = "nonexistent"\n')

        result = discover_source_paths(tmp_path)

        assert result == []

    def it_filters_nonexistent_find_where(self, tmp_path):
        """Only returns find.where values whose directories exist."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.packages.find]\nwhere = ["missing"]\n')

        result = discover_source_paths(tmp_path)

        assert result == []

    def it_deduplicates_discovered_paths(self, tmp_path):
        """Does not return duplicate paths from multiple sources."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.package-dir]\n"" = "lib"\nmypkg = "lib"\n')
        (tmp_path / 'lib').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('lib')]

    def it_handles_empty_setuptools_section(self, tmp_path):
        """Returns empty list when [tool.setuptools] is empty."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\n')

        result = discover_source_paths(tmp_path)

        assert result == []

    def it_package_dir_with_named_package(self, tmp_path):
        """Reads package-dir with named package mapping."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.package-dir]\nmypkg = "src/mypkg"\n')
        (tmp_path / 'src' / 'mypkg').mkdir(parents=True)

        result = discover_source_paths(tmp_path)

        assert result == [Path('src/mypkg')]

    def it_resolves_nested_dotted_package_to_top_level_directory(self, tmp_path):
        """Resolves dotted package name to its top-level directory."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp.utils"]\n')
        (tmp_path / 'cogapp' / 'utils').mkdir(parents=True)

        result = discover_source_paths(tmp_path)

        assert result == [Path('cogapp')]

    def it_find_where_as_string_discovered(self, tmp_path):
        """Discovers source path when find.where is a string instead of a list."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.packages.find]\nwhere = "src"\n')
        (tmp_path / 'src').mkdir()

        result = discover_source_paths(tmp_path)

        assert result == [Path('src')]

    def it_malformed_toml_returns_empty_list(self, tmp_path):
        """Returns empty list when pyproject.toml contains invalid TOML."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools\npackages = ["broken"')

        result = discover_source_paths(tmp_path)

        assert result == []

    def it_package_dir_empty_string_value_excluded(self, tmp_path):
        """Excludes empty string values from package-dir mapping."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools.package-dir]\nmypackage = ""\n')

        result = discover_source_paths(tmp_path)

        assert result == []
