"""Operator-owner lookup handles editable installs and nameless distributions (#873)."""

from __future__ import annotations

from collections import Counter
import importlib
from importlib.metadata import PathDistribution
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_gremlins.operators.protocol import GremlinOperator

OPERATOR_SOURCE = 'class OwnedOperator:\n    name = "owned"\n'
MODULES = (
    'broken_dist_ops',
    'editable_ops',
    'nameless_ops',
    'qa_tests_pkg',
    'qa_badurl_ops',
    'qa_cost_a',
    'qa_cost_b',
    'qa_cost_c',
    'direct_url_ops',
)


def _operator_from(module: str) -> GremlinOperator:
    operator: GremlinOperator = importlib.import_module(module).OwnedOperator()
    return operator


def _dist_info(site: Path, name: str, record: str) -> Path:
    dist_info = site / f'{name}-1.0.dist-info'
    dist_info.mkdir()
    (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n')
    (dist_info / 'RECORD').write_text(record)
    return dist_info


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / 'site'
    path.mkdir()
    monkeypatch.syspath_prepend(str(path))
    yield path
    for module in MODULES:
        sys.modules.pop(module, None)


@pytest.mark.medium
class DescribeOperatorOwnerLookupGaps:
    def it_adds_nothing_for_a_pth_only_editable_install(
        self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Documented limitation: only PEP 610 direct_url.json marks an editable install; a bare .pth does not.
        src = tmp_path / 'editable_src'
        src.mkdir()
        (src / 'editable_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(src))
        _dist_info(site, 'editable_ops_dist', '_editable_ops_dist.pth,,\neditable_ops_dist-1.0.dist-info/RECORD,,\n')
        (site / '_editable_ops_dist.pth').write_text(f'{src}\n')
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('editable_ops')])

        assert 'editable_ops_dist' not in fingerprint

    def it_never_reads_pth_files(self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / 'editable_src'
        src.mkdir()
        (src / 'editable_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(src))
        _dist_info(site, 'pth_dist', '_pth_dist.pth,,\npth_dist-1.0.dist-info/RECORD,,\n')
        (site / '_pth_dist.pth').write_bytes('/opt/caf\xe9/src\n'.encode('latin-1'))
        importlib.invalidate_caches()
        read_names: list[str] = []
        original = PathDistribution.read_text

        def recording_read_text(self: PathDistribution, filename: str) -> str | None:
            read_names.append(filename)
            return original(self, filename)

        monkeypatch.setattr(PathDistribution, 'read_text', recording_read_text)

        installed_versions_fingerprint([_operator_from('editable_ops')])

        assert not any(name.endswith('.pth') for name in read_names)

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
        (dist_info / 'top_level.txt').write_text('editable_ops\n')
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

    def it_adds_nothing_for_an_operator_under_the_rootdir_of_an_editable_project(
        self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # uv sync installs the project under test editable; its direct_url.json names the repo root.
        project = tmp_path / 'project'
        (project / 'qa_tests_pkg').mkdir(parents=True)
        (project / 'qa_tests_pkg' / '__init__.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(project))
        dist_info = _dist_info(site, 'qa_project_under_test', 'qa_project_under_test-1.0.dist-info/RECORD,,\n')
        (dist_info / 'direct_url.json').write_text(
            json.dumps({'url': project.as_uri(), 'dir_info': {'editable': True}})
        )
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('qa_tests_pkg')], project_root=project)

        assert 'qa_project_under_test' not in fingerprint

    def it_survives_an_unrelated_editable_distribution_with_a_non_string_url(
        self, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / 'local'
        local.mkdir()
        (local / 'qa_badurl_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(local))
        dist_info = _dist_info(site, 'qa_badurl_dist', 'qa_badurl_dist-1.0.dist-info/RECORD,,\n')
        (dist_info / 'direct_url.json').write_text(json.dumps({'url': 5, 'dir_info': {'editable': True}}))
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('qa_badurl_ops')])

        assert 'qa_badurl_dist' not in fingerprint

    def it_reads_each_distribution_record_at_most_once_for_several_operators_no_distribution_owns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / 'local'
        local.mkdir()
        names = ('qa_cost_a', 'qa_cost_b', 'qa_cost_c')
        for name in names:
            (local / f'{name}.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(local))
        importlib.invalidate_caches()
        operators = [_operator_from(name) for name in names]
        reads: Counter[str] = Counter()
        original = PathDistribution.read_text

        def counting_read_text(self: PathDistribution, filename: str) -> str | None:
            if filename == 'RECORD':
                reads[str(self._path)] += 1
            return original(self, filename)

        monkeypatch.setattr(PathDistribution, 'read_text', counting_read_text)

        installed_versions_fingerprint(operators)

        assert reads
        assert max(reads.values()) <= 1


def _install_owner_with_raw_direct_url(site: Path, direct_url: bytes | None) -> None:
    """Lay out an installed owner of ``direct_url_ops`` the way pip/uv do (RECORD, no top_level.txt)."""
    package = site / 'direct_url_ops'
    package.mkdir()
    (package / '__init__.py').write_text(OPERATOR_SOURCE)
    dist_info = _dist_info(
        site, 'direct-url-dist', 'direct_url_ops/__init__.py,,\ndirect_url_dist-1.0.dist-info/RECORD,,\n'
    )
    if direct_url is not None:
        (dist_info / 'direct_url.json').write_bytes(direct_url)
    importlib.invalidate_caches()


def _install_owner(site: Path, direct_url: dict[str, object] | None) -> None:
    raw = None if direct_url is None else json.dumps(direct_url).encode()
    _install_owner_with_raw_direct_url(site, raw)


NON_EDITABLE_DIRECT_URLS: dict[str, dict[str, object]] = {
    'local_directory': {'url': 'file:///somewhere/direct-url-dist', 'dir_info': {}},
    'explicit_not_editable': {'url': 'file:///somewhere/direct-url-dist', 'dir_info': {'editable': False}},
    'vcs': {'url': 'https://example.com/direct-url-dist.git', 'vcs_info': {'vcs': 'git', 'commit_id': 'a' * 40}},
    'archive': {'url': 'file:///somewhere/direct_url_dist-1.0-py3-none-any.whl', 'archive_info': {}},
}


@pytest.mark.medium
class DescribeOwnersInstalledFromADirectUrl:
    @pytest.mark.parametrize('shape', sorted(NON_EDITABLE_DIRECT_URLS))
    def it_labels_the_owner_of_a_non_editable_direct_url_install(self, shape: str, site: Path) -> None:
        _install_owner(site, NON_EDITABLE_DIRECT_URLS[shape])

        fingerprint = installed_versions_fingerprint([_operator_from('direct_url_ops')])

        assert 'direct-url-dist==1.0' in fingerprint

    def it_labels_the_owner_of_an_index_install_without_a_direct_url(self, site: Path) -> None:
        _install_owner(site, None)

        fingerprint = installed_versions_fingerprint([_operator_from('direct_url_ops')])

        assert 'direct-url-dist==1.0' in fingerprint


MALFORMED_DIRECT_URLS: dict[str, bytes] = {
    'not-utf8': b'\xff{}',
    'not-an-object': b'[1]',
    'dir-info-not-an-object': json.dumps({'url': 'file:///x', 'dir_info': 'str'}).encode(),
    'url-not-a-string': json.dumps({'url': 5, 'dir_info': {'editable': True}}).encode(),
    'unbalanced-ipv6-host': b'{"url": "file://[::1/x", "dir_info": {"editable": true}}',
    'nul-byte-path': b'{"url": "file:///tmp/a\\u0000b", "dir_info": {"editable": true}}',
    'deeply-nested': b'[' * 100_000 + b']' * 100_000,
}


@pytest.mark.medium
class DescribeOwnersWithAMalformedDirectUrl:
    @pytest.mark.parametrize('shape', sorted(MALFORMED_DIRECT_URLS))
    def it_labels_the_owner_despite_a_malformed_direct_url(self, shape: str, site: Path) -> None:
        _install_owner_with_raw_direct_url(site, MALFORMED_DIRECT_URLS[shape])

        fingerprint = installed_versions_fingerprint([_operator_from('direct_url_ops')])

        assert 'direct-url-dist==1.0' in fingerprint


META = b'Metadata-Version: 2.1\nName: brokenpkg\nVersion: 1.0\n'
BROKEN_DIST_INFO_FILES: dict[str, dict[str, bytes]] = {
    'no_metadata': {},
    'record_with_four_fields': {'METADATA': META, 'RECORD': b'a.py,,,extra\n'},
    'record_with_non_integer_size': {'METADATA': META, 'RECORD': b'a.py,,notint\n'},
    'top_level_not_utf8': {'METADATA': META, 'top_level.txt': b'\xff\xfe\x00bad'},
    'metadata_not_utf8': {'METADATA': b'Name: \xff\n'},
}


def _write_files(directory: Path, files: dict[str, bytes]) -> None:
    for filename, content in files.items():
        (directory / filename).write_bytes(content)


@pytest.mark.medium
class DescribeBrokenDistributionMetadata:
    @pytest.mark.filterwarnings('error')
    @pytest.mark.parametrize('shape', sorted(BROKEN_DIST_INFO_FILES))
    def it_skips_a_distribution_with_unreadable_metadata(
        self, shape: str, tmp_path: Path, site: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / 'local'
        local.mkdir()
        (local / 'broken_dist_ops.py').write_text(OPERATOR_SOURCE)
        monkeypatch.syspath_prepend(str(local))
        dist_info = site / 'brokenpkg-1.0.dist-info'
        dist_info.mkdir()
        _write_files(dist_info, BROKEN_DIST_INFO_FILES[shape])
        importlib.invalidate_caches()

        fingerprint = installed_versions_fingerprint([_operator_from('broken_dist_ops')])

        assert fingerprint.startswith('cache-version=')
