"""Install-record ownership (#890): flat-layout PEP 660 editables, ``.pth`` reading and the read-once invariant."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
import importlib
from importlib.metadata import PathDistribution
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
class DescribeInstallRecordOwnership:
    def it_misses_for_a_tools_helper_under_a_flat_layout_pep660_editable_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A flat-layout editable (no ``top_level.txt``) whose ``.pth`` lists the project directory claims no names.

        Every sibling of the package, such as ``tools``, sits directly in that directory, so none is the
        distribution's own module and ``tools/helper.py`` must not key on ``edpkg-q4==3.0``.
        """
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

    def it_keeps_a_stable_key_for_a_recorded_operator_of_a_wheel_shipping_a_non_utf8_pth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wheel with no ``top_level.txt`` and a non-UTF-8 ``.pth`` keeps its label for a recorded operator."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _write(site / 'whlpkg_q5' / '__init__.py', '')
        _write(site / 'whlpkg_q5' / 'ops.py', OPERATOR_SOURCE)
        info = site / 'whlpkg_q5-1.0.dist-info'
        _write(info / 'METADATA', 'Metadata-Version: 2.1\nName: whlpkg-q5\nVersion: 1.0\n')
        _write(
            info / 'RECORD',
            'whlpkg_q5/__init__.py,,\nwhlpkg_q5/ops.py,,\nwhlpkg_q5.pth,,\nwhlpkg_q5-1.0.dist-info/RECORD,,\n',
        )
        (site / 'whlpkg_q5.pth').write_bytes('/opt/caf\xe9/extra\n'.encode('latin-1'))
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('whlpkg_q5.ops').HelperOperator()

        assert 'whlpkg-q5==1.0' in installed_versions_fingerprint([operator], rootdir)

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
