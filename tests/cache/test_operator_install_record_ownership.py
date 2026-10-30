"""Install-record ownership (#890): editables without ``top_level.txt`` own nothing; install records are read once."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import importlib
from importlib.metadata import (
    Distribution,
    PathDistribution,
)
import json
import os
from pathlib import Path
import sys
from typing import Any
import zipfile

import pytest

from pytest_gremlins.cache import versions
from pytest_gremlins.cache.versions import installed_versions_fingerprint

OPERATOR_SOURCE = 'class HelperOperator:\n    name = "helper"\n    description = "v1"\n'
OVERSIZED_FIELD = 'x' * 200_000


@pytest.fixture
def isolated_modules() -> Iterator[None]:
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _installed_package(site: Path, name: str, record: str, *, top_level: bool) -> None:
    _write(site / name / '__init__.py', '')
    _write(site / name / 'ops.py', OPERATOR_SOURCE)
    info = site / f'{name}-1.0.dist-info'
    _write(info / 'METADATA', f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n')
    _write(info / 'RECORD', record)
    if top_level:
        _write(info / 'top_level.txt', f'{name}\n')


class _PathlessDistribution(Distribution):
    """A distribution from a custom finder: it reads files from a directory but has no ``_path`` attribute."""

    def __init__(self, directory: Path, root: Path) -> None:
        self._directory = directory
        self._root = root

    def read_text(self, filename: str) -> str | None:
        target = self._directory / filename
        return target.read_text() if target.is_file() else None

    def locate_file(self, path: str | os.PathLike[str]) -> Path:
        return self._root / path


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

    def it_does_not_crash_on_a_record_field_over_the_csv_size_limit_without_top_level_txt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt RECORD row longer than ``csv.field_size_limit()`` raises ``csv.Error``, not a ValueError."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _installed_package(site, 'csvpkg_a4', f'csvpkg_a4/ops.py,,\n{OVERSIZED_FIELD},,\n', top_level=False)
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('csvpkg_a4.ops').HelperOperator()

        fingerprint = installed_versions_fingerprint([operator], rootdir)

        assert fingerprint.startswith('cache-version=')

    def it_does_not_crash_on_a_record_field_over_the_csv_size_limit_with_top_level_txt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ``top_level.txt`` the RECORD is first parsed lazily in ``paths``, outside any handler."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _installed_package(site, 'csvpkg_b4', f'csvpkg_b4/ops.py,,\n{OVERSIZED_FIELD},,\n', top_level=True)
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('csvpkg_b4.ops').HelperOperator()

        fingerprint = installed_versions_fingerprint([operator], rootdir)

        assert fingerprint.startswith('cache-version=')

    def it_does_not_crash_on_a_record_entry_through_a_symlink_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``Path.resolve()`` raises RuntimeError on a symlink loop on Python 3.11 and 3.12."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _installed_package(site, 'looppkg_c4', 'looppkg_c4/ops.py,,\nlooppkg_c4/loop/x.py,,\n', top_level=True)
        (site / 'looppkg_c4' / 'loop').symlink_to('loop')
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('looppkg_c4.ops').HelperOperator()

        fingerprint = installed_versions_fingerprint([operator], rootdir)

        assert fingerprint.startswith('cache-version=')

    def it_misses_without_crashing_on_a_non_utf8_record_with_top_level_txt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _installed_package(site, 'binpkg_d4', '', top_level=True)
        (site / 'binpkg_d4-1.0.dist-info' / 'RECORD').write_bytes(b'binpkg_d4/ops.py,,\n\xff\xfe,,\n')
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('binpkg_d4.ops').HelperOperator()

        assert 'binpkg_d4==1.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_a_whitespace_only_record(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _installed_package(site, 'blankpkg_e4', ' \n\t\n', top_level=True)
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('blankpkg_e4.ops').HelperOperator()

        assert 'blankpkg_e4==1.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_without_crashing_for_an_egg_info_distribution_without_a_path_attribute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A custom finder's distribution has no ``_path``, so ``installed-files.txt`` cannot be anchored."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _write(site / 'nopath_f4' / '__init__.py', '')
        _write(site / 'nopath_f4' / 'ops.py', OPERATOR_SOURCE)
        egg_info = site / 'nopath_f4-1.0.egg-info'
        _write(egg_info / 'PKG-INFO', 'Metadata-Version: 2.1\nName: nopath-f4\nVersion: 1.0\n')
        _write(egg_info / 'top_level.txt', 'nopath_f4\n')
        _write(egg_info / 'installed-files.txt', '../nopath_f4/__init__.py\n../nopath_f4/ops.py\n')
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.setattr(versions, 'distributions', lambda: [_PathlessDistribution(egg_info, site)])
        operator = importlib.import_module('nopath_f4.ops').HelperOperator()

        assert 'nopath-f4==1.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_keeps_the_version_label_for_a_zipped_wheel_on_sys_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #890 AC: zip installs keep their version label."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        archive = tmp_path / 'zippkg_g4-1.0-py3-none-any.whl'
        with zipfile.ZipFile(archive, 'w') as wheel:
            wheel.writestr('zippkg_g4/__init__.py', '')
            wheel.writestr('zippkg_g4/ops.py', OPERATOR_SOURCE)
            wheel.writestr('zippkg_g4-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: zippkg-g4\nVersion: 1.0\n')
            wheel.writestr('zippkg_g4-1.0.dist-info/RECORD', 'zippkg_g4/__init__.py,,\nzippkg_g4/ops.py,,\n')
        monkeypatch.syspath_prepend(str(archive))
        operator = importlib.import_module('zippkg_g4.ops').HelperOperator()

        assert 'zippkg-g4==1.0' in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_an_operator_in_an_egg_directory_on_sys_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision on #890: a real ``EGG-INFO`` has no install record, so no record proves ownership."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        egg = tmp_path / 'eggpkg_h4-1.0-py3.12.egg'
        _write(egg / 'eggpkg_h4' / '__init__.py', '')
        _write(egg / 'eggpkg_h4' / 'ops.py', OPERATOR_SOURCE)
        _write(egg / 'EGG-INFO' / 'PKG-INFO', 'Metadata-Version: 2.1\nName: eggpkg-h4\nVersion: 1.0\n')
        _write(egg / 'EGG-INFO' / 'top_level.txt', 'eggpkg_h4\n')
        _write(egg / 'EGG-INFO' / 'SOURCES.txt', 'eggpkg_h4/__init__.py\neggpkg_h4/ops.py\n')
        monkeypatch.syspath_prepend(str(egg))
        operator = importlib.import_module('eggpkg_h4.ops').HelperOperator()

        assert 'eggpkg-h4==1.0' not in installed_versions_fingerprint([operator], rootdir)
