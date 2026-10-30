"""Install-record ownership (#890): empty install records and editables without ``top_level.txt``."""

from __future__ import annotations

from collections.abc import Iterator
import importlib
import json
from pathlib import Path
import sys

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

OPERATOR_SOURCE = 'class HelperOperator:\n    name = "helper"\n    description = "v1"\n'


@pytest.fixture
def isolated_modules() -> Iterator[None]:
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.medium
@pytest.mark.usefixtures('isolated_modules')
class DescribeInstallRecordOwnershipEdgeCases:
    def it_misses_for_a_pep660_editable_without_top_level_txt_outside_the_rootdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A PEP 660 editable with no ``top_level.txt`` (hatchling, uv_build, flit, pdm) owns no names."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        plugin = tmp_path / 'plugin_checkout'
        _write(plugin / 'src' / 'hedpkg_q1' / '__init__.py', '')
        _write(plugin / 'src' / 'hedpkg_q1' / 'ops.py', OPERATOR_SOURCE)
        site = tmp_path / 'site'
        info = site / 'hedpkg_q1-2.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: hedpkg-q1\nVersion: 2.0\n')
        _write(
            info / 'RECORD',
            '_editable_impl_hedpkg_q1.pth,,\nhedpkg_q1-2.0.dist-info/METADATA,,\nhedpkg_q1-2.0.dist-info/RECORD,,\n',
        )
        _write(info / 'direct_url.json', json.dumps({'url': plugin.as_uri(), 'dir_info': {'editable': True}}))
        _write(site / '_editable_impl_hedpkg_q1.pth', f'{plugin / "src"}\n')
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.syspath_prepend(str(plugin / 'src'))
        operator = importlib.import_module('hedpkg_q1.ops').HelperOperator()

        assert 'hedpkg-q1==2.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_a_source_egg_info_whose_installed_files_txt_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty ``installed-files.txt`` is no install record, so ``SOURCES.txt`` must not stand in for it."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        src = tmp_path / 'sibling' / 'src'
        _write(src / 'sibpkg_q2' / '__init__.py', '')
        _write(src / 'sibpkg_q2' / 'ops.py', OPERATOR_SOURCE)
        egg_info = src / 'sibpkg_q2.egg-info'
        _write(egg_info / 'PKG-INFO', 'Metadata-Version: 2.1\nName: sibpkg-q2\nVersion: 0.1\n')
        _write(egg_info / 'top_level.txt', 'sibpkg_q2\n')
        _write(egg_info / 'SOURCES.txt', 'sibpkg_q2/__init__.py\nsibpkg_q2/ops.py\n')
        _write(egg_info / 'installed-files.txt', '')
        monkeypatch.syspath_prepend(str(src))
        operator = importlib.import_module('sibpkg_q2.ops').HelperOperator()

        assert 'sibpkg-q2==0.1' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_a_source_egg_info_with_an_empty_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty ``RECORD`` is no install record, so ``SOURCES.txt`` must not stand in for it."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        src = tmp_path / 'sibling' / 'src'
        _write(src / 'sibpkg_q3' / '__init__.py', '')
        _write(src / 'sibpkg_q3' / 'ops.py', OPERATOR_SOURCE)
        egg_info = src / 'sibpkg_q3.egg-info'
        _write(egg_info / 'PKG-INFO', 'Metadata-Version: 2.1\nName: sibpkg-q3\nVersion: 0.1\n')
        _write(egg_info / 'top_level.txt', 'sibpkg_q3\n')
        _write(egg_info / 'SOURCES.txt', 'sibpkg_q3/__init__.py\nsibpkg_q3/ops.py\n')
        _write(egg_info / 'RECORD', '')
        monkeypatch.syspath_prepend(str(src))
        operator = importlib.import_module('sibpkg_q3.ops').HelperOperator()

        assert 'sibpkg-q3==0.1' not in installed_versions_fingerprint([operator], rootdir)
