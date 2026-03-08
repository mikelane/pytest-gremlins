"""Tests for source path discovery via importlib.metadata."""

import importlib.util
import types

import pytest

from pytest_gremlins.config import discover_by_importlib_metadata


@pytest.mark.small
class DescribeDiscoverByImportlibMetadata:
    """Tests for discover_by_importlib_metadata function."""

    def it_returns_empty_when_no_packages_match_rootdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            lambda: {'somepackage': ['some-dist']},
        )

        result = discover_by_importlib_metadata(tmp_path)

        assert result == []

    def it_discovers_installed_package_under_rootdir(self, tmp_path, monkeypatch):
        pkg_dir = tmp_path / 'my_package'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('')

        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            lambda: {'my_package': ['my-package']},
        )

        fake_spec = types.SimpleNamespace(origin=str(pkg_dir / '__init__.py'))
        orig_find_spec = importlib.util.find_spec

        def patched_find_spec(name):
            if name == 'my_package':
                return fake_spec
            return orig_find_spec(name)

        monkeypatch.setattr(importlib.util, 'find_spec', patched_find_spec)

        result = discover_by_importlib_metadata(tmp_path)

        assert result == ['my_package']

    def it_excludes_venv_directories_inside_rootdir(self, tmp_path, monkeypatch):
        venv_pkg = tmp_path / '.venv' / 'lib' / 'python3.12' / 'site-packages' / 'requests'
        venv_pkg.mkdir(parents=True)
        (venv_pkg / '__init__.py').write_text('')

        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            lambda: {'requests': ['requests']},
        )

        fake_spec = types.SimpleNamespace(origin=str(venv_pkg / '__init__.py'))
        monkeypatch.setattr(importlib.util, 'find_spec', lambda name: fake_spec if name == 'requests' else None)

        result = discover_by_importlib_metadata(tmp_path)

        assert result == []

    def it_skips_package_when_find_spec_raises(self, tmp_path, monkeypatch):
        pkg_dir = tmp_path / 'good_pkg'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('')

        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            lambda: {'bad_pkg': ['bad-dist'], 'good_pkg': ['good-dist']},
        )

        fake_spec = types.SimpleNamespace(origin=str(pkg_dir / '__init__.py'))

        def patched_find_spec(name):
            if name == 'bad_pkg':
                raise ImportError('cannot import')
            if name == 'good_pkg':
                return fake_spec
            return None

        monkeypatch.setattr(importlib.util, 'find_spec', patched_find_spec)

        result = discover_by_importlib_metadata(tmp_path)

        assert 'good_pkg' in result
        assert 'bad_pkg' not in result

    def it_skips_package_not_relative_to_rootdir(self, tmp_path, monkeypatch):
        outside_dir = tmp_path.parent / 'other_project' / 'some_pkg'
        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            lambda: {'some_pkg': ['some-dist']},
        )

        fake_spec = types.SimpleNamespace(origin=str(outside_dir / '__init__.py'))
        monkeypatch.setattr(importlib.util, 'find_spec', lambda name: fake_spec if name == 'some_pkg' else None)

        result = discover_by_importlib_metadata(tmp_path)

        assert result == []

    def it_returns_empty_on_exception(self, tmp_path, monkeypatch):
        def raise_error():
            raise RuntimeError('metadata unavailable')

        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            raise_error,
        )

        result = discover_by_importlib_metadata(tmp_path)

        assert result == []
