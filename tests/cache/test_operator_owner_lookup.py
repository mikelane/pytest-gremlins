"""Operator-owner lookup handles editable installs and nameless distributions (#873)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
from typing import (
    TYPE_CHECKING,
    Any,
)

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from collections.abc import Iterator

OPERATOR_SOURCE = 'class OwnedOperator:\n    name = "owned"\n'


def _operator_from(module: str) -> Any:
    return importlib.import_module(module).OwnedOperator()


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / 'site'
    path.mkdir()
    monkeypatch.syspath_prepend(str(path))
    yield path
    for module in ('editable_ops', 'nameless_ops'):
        sys.modules.pop(module, None)


@pytest.mark.medium
class DescribeOperatorOwnerLookupGaps:
    def it_names_an_editable_install_that_owns_a_registered_operator(
        self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Shape of a uv/pip editable install: RECORD lists a .pth, not the package's modules.
        src = tmp_path / 'editable_src'
        src.mkdir()
        (src / 'editable_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(src))
        dist_info = site / 'editable_ops_dist-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: editable_ops_dist\nVersion: 1.0\n')
        (dist_info / 'RECORD').write_text(
            '_editable_ops_dist.pth,,\n'
            'editable_ops_dist-1.0.dist-info/METADATA,,\n'
            'editable_ops_dist-1.0.dist-info/RECORD,,\n'
        )
        (site / '_editable_ops_dist.pth').write_text(f'{src}\n')
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('editable_ops')])

        assert 'editable_ops_dist==1.0' in fingerprint

    def it_names_a_pep610_editable_install_that_owns_a_registered_operator(
        self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / 'project'
        (project / 'src').mkdir(parents=True)
        (project / 'src' / 'editable_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(project / 'src'))
        dist_info = site / 'editable_ops_dist-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: editable_ops_dist\nVersion: 1.0\n')
        (dist_info / 'direct_url.json').write_text(
            json.dumps({'url': project.as_uri(), 'dir_info': {'editable': True}})
        )
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('editable_ops')])

        assert 'editable_ops_dist==1.0' in fingerprint

    @pytest.mark.filterwarnings('error')
    def it_fingerprints_a_nameless_distribution_that_owns_a_registered_operator(self, site: Path) -> None:
        dist_info = site / 'nameless_ops-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\n')
        (dist_info / 'RECORD').write_text('nameless_ops.py,,\nnameless_ops-1.0.dist-info/METADATA,,\n')
        (site / 'nameless_ops.py').write_text(OPERATOR_SOURCE)
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('nameless_ops')])

        assert 'nameless_ops' in fingerprint
