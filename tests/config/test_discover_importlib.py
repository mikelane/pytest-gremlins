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

    def it_returns_empty_on_exception(self, tmp_path, monkeypatch):
        def raise_error():
            raise RuntimeError('metadata unavailable')

        monkeypatch.setattr(
            'pytest_gremlins.config._packages_distributions',
            raise_error,
        )

        result = discover_by_importlib_metadata(tmp_path)

        assert result == []
