"""Install-record ownership (#890): editables without ``top_level.txt`` own nothing; install records are read once."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import importlib
from importlib.metadata import PathDistribution
import json
from pathlib import Path
import sys
from typing import Any

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
class DescribeInstallRecordOwnership:
    def it_misses_for_a_tools_helper_beside_an_editable_without_top_level_txt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An editable with no ``top_level.txt`` owns no names, so ``tools/helper.py`` misses."""
        workspace = tmp_path / 'workspace'
        rootdir = workspace / 'member'
        rootdir.mkdir(parents=True)
        _write(workspace / 'edpkg_q4' / '__init__.py', '')
        _write(workspace / 'tools_q4' / '__init__.py', '')
        _write(workspace / 'tools_q4' / 'helper.py', OPERATOR_SOURCE)
        site = tmp_path / 'site'
        info = site / 'edpkg_q4-3.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: edpkg-q4\nVersion: 3.0\n')
        _write(info / 'RECORD', '_edpkg_q4.pth,,\nedpkg_q4-3.0.dist-info/METADATA,,\nedpkg_q4-3.0.dist-info/RECORD,,\n')
        _write(info / 'direct_url.json', json.dumps({'url': workspace.as_uri(), 'dir_info': {'editable': True}}))
        _write(site / '_edpkg_q4.pth', f'{workspace}\n')
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.syspath_prepend(str(workspace))
        operator = importlib.import_module('tools_q4.helper').HelperOperator()

        assert 'edpkg-q4==3.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_a_src_sibling_package_a_hatchling_editable_does_not_ship(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hatchling src-layout editable lists ``src`` in its ``.pth``, which also holds dirs the wheel omits."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        checkout = tmp_path / 'checkout'
        _write(checkout / 'src' / 'realpkg_s1' / '__init__.py', '')
        _write(checkout / 'src' / 'scratch_s1' / '__init__.py', '')
        _write(checkout / 'src' / 'scratch_s1' / 'ops.py', OPERATOR_SOURCE)
        site = tmp_path / 'site'
        info = site / 'realpkg_s1-1.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: realpkg-s1\nVersion: 1.0\n')
        _write(
            info / 'RECORD',
            '_editable_impl_realpkg_s1.pth,,\nrealpkg_s1-1.0.dist-info/METADATA,,\nrealpkg_s1-1.0.dist-info/RECORD,,\n',
        )
        _write(info / 'direct_url.json', json.dumps({'url': checkout.as_uri(), 'dir_info': {'editable': True}}))
        _write(site / '_editable_impl_realpkg_s1.pth', f'{checkout / "src"}\n')
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.syspath_prepend(str(checkout / 'src'))
        operator = importlib.import_module('scratch_s1.ops').HelperOperator()

        assert 'realpkg-s1==1.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_never_reads_a_pth_file_of_an_editable_without_top_level_txt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No metadata says which children of a ``.pth`` directory ship, so the ``.pth`` is not consulted."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        checkout = tmp_path / 'checkout'
        _write(checkout / 'src' / 'pthpkg_s3' / '__init__.py', '')
        _write(checkout / 'src' / 'pthpkg_s3' / 'ops.py', OPERATOR_SOURCE)
        site = tmp_path / 'site'
        info = site / 'pthpkg_s3-1.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: pthpkg-s3\nVersion: 1.0\n')
        _write(info / 'RECORD', '_editable_impl_pthpkg_s3.pth,,\npthpkg_s3-1.0.dist-info/RECORD,,\n')
        _write(info / 'direct_url.json', json.dumps({'url': checkout.as_uri(), 'dir_info': {'editable': True}}))
        _write(site / '_editable_impl_pthpkg_s3.pth', f'{checkout / "src"}\n')
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.syspath_prepend(str(checkout / 'src'))
        operator = importlib.import_module('pthpkg_s3.ops').HelperOperator()
        opened: list[str] = []
        original = Path.read_text

        def recording_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            opened.append(self.name)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, 'read_text', recording_read_text)

        installed_versions_fingerprint([operator], rootdir)

        assert '_editable_impl_pthpkg_s3.pth' not in opened

    def it_reads_each_distribution_record_at_most_once_for_several_operators_one_distribution_owns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The install record is read once per distribution, however many operators it owns."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        names = ('ops_a', 'ops_b', 'ops_c')
        for name in names:
            _write(site / 'multipkg_q6' / f'{name}.py', OPERATOR_SOURCE)
        _write(site / 'multipkg_q6' / '__init__.py', '')
        info = site / 'multipkg_q6-1.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: multipkg-q6\nVersion: 1.0\n')
        record = ''.join(f'multipkg_q6/{name}.py,,\n' for name in names)
        _write(info / 'RECORD', f'multipkg_q6/__init__.py,,\n{record}multipkg_q6-1.0.dist-info/RECORD,,\n')
        monkeypatch.syspath_prepend(str(site))
        operators = [importlib.import_module(f'multipkg_q6.{name}').HelperOperator() for name in names]
        reads: Counter[str] = Counter()
        original = PathDistribution.read_text

        def counting_read_text(self: PathDistribution, filename: str) -> str | None:
            if filename == 'RECORD' and 'multipkg_q6' in str(self._path):
                reads[str(self._path)] += 1
            return original(self, filename)

        monkeypatch.setattr(PathDistribution, 'read_text', counting_read_text)

        installed_versions_fingerprint(operators, rootdir)

        assert max(reads.values()) <= 1

    def it_reads_an_egg_info_installed_files_record_at_most_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy ``pip install`` egg-info's ``installed-files.txt`` is read once, like a dist-info ``RECORD``."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _write(site / 'legpkg_s2' / '__init__.py', '')
        _write(site / 'legpkg_s2' / 'ops.py', OPERATOR_SOURCE)
        egg_info = site / 'legpkg_s2-1.0-py3.12.egg-info'
        _write(egg_info / 'PKG-INFO', 'Metadata-Version: 2.1\nName: legpkg-s2\nVersion: 1.0\n')
        _write(egg_info / 'top_level.txt', 'legpkg_s2\n')
        _write(egg_info / 'installed-files.txt', '../legpkg_s2/__init__.py\n../legpkg_s2/ops.py\nPKG-INFO\n')
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('legpkg_s2.ops').HelperOperator()
        reads: Counter[str] = Counter()
        original = PathDistribution.read_text

        def counting_read_text(self: PathDistribution, filename: str) -> str | None:
            if 'legpkg_s2' in str(self._path):
                reads[filename] += 1
            return original(self, filename)

        monkeypatch.setattr(PathDistribution, 'read_text', counting_read_text)

        installed_versions_fingerprint([operator], rootdir)

        assert reads['installed-files.txt'] <= 1

    def it_keeps_a_stable_key_for_an_operator_listed_in_an_egg_info_installed_files_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``installed-files.txt`` paths are relative to the ``.egg-info`` directory, so ``../pkg/x.py`` is owned."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _write(site / 'legpkg_s4' / '__init__.py', '')
        _write(site / 'legpkg_s4' / 'ops.py', OPERATOR_SOURCE)
        egg_info = site / 'legpkg_s4-1.0-py3.12.egg-info'
        _write(egg_info / 'PKG-INFO', 'Metadata-Version: 2.1\nName: legpkg-s4\nVersion: 1.0\n')
        _write(egg_info / 'top_level.txt', 'legpkg_s4\n')
        _write(egg_info / 'installed-files.txt', '../legpkg_s4/__init__.py\n../legpkg_s4/ops.py\nPKG-INFO\n')
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('legpkg_s4.ops').HelperOperator()

        assert 'legpkg-s4==1.0' in installed_versions_fingerprint([operator], rootdir)
