"""Tests for source path discovery via [project].name heuristic in pyproject.toml."""

from pathlib import Path

import pytest

from pytest_gremlins.config import discover_by_project_name


@pytest.mark.medium
class DescribeDiscoverByProjectName:
    """Tests for discover_by_project_name function."""

    def it_returns_empty_when_no_pyproject_toml(self, tmp_path):
        result = discover_by_project_name(tmp_path)

        assert result == []

    def it_returns_empty_when_no_project_name(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\n')

        result = discover_by_project_name(tmp_path)

        assert result == []

    def it_discovers_normalized_package_name(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my-pkg"\n')
        pkg = tmp_path / 'my_pkg'
        pkg.mkdir()
        (pkg / '__init__.py').write_text('')

        result = discover_by_project_name(tmp_path)

        assert result == [Path('my_pkg')]

    def it_discovers_src_layout_package(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my-pkg"\n')
        src_pkg = tmp_path / 'src' / 'my_pkg'
        src_pkg.mkdir(parents=True)
        (src_pkg / '__init__.py').write_text('')

        result = discover_by_project_name(tmp_path)

        assert result == [Path('src/my_pkg')]

    def it_prefers_root_over_src_layout(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my-pkg"\n')
        root_pkg = tmp_path / 'my_pkg'
        root_pkg.mkdir()
        (root_pkg / '__init__.py').write_text('')
        src_pkg = tmp_path / 'src' / 'my_pkg'
        src_pkg.mkdir(parents=True)
        (src_pkg / '__init__.py').write_text('')

        result = discover_by_project_name(tmp_path)

        assert result == [Path('my_pkg')]

    def it_requires_init_py(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my-pkg"\n')
        (tmp_path / 'my_pkg').mkdir()

        result = discover_by_project_name(tmp_path)

        assert result == []

    def it_normalizes_dots_in_name(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my.pkg"\n')
        pkg = tmp_path / 'my_pkg'
        pkg.mkdir()
        (pkg / '__init__.py').write_text('')

        result = discover_by_project_name(tmp_path)

        assert result == [Path('my_pkg')]

    def it_returns_empty_when_dir_does_not_exist(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "my-pkg"\n')

        result = discover_by_project_name(tmp_path)

        assert result == []
