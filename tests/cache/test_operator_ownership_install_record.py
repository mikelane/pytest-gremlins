"""An operator keeps a stable cache key only when an installed distribution's install record lists its file (#890).

Each test builds an operator module that is importable by its qualified name but whose FILE no installed
distribution owns, and asserts that such an operator gets the always-miss token, so two fingerprints of the
same run differ.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib
import importlib.util
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


def _dist_info(site: Path, name: str, version: str, record: str, extra: dict[str, str] | None = None) -> None:
    info = site / f'{name}-{version}.dist-info'
    _write(info / 'METADATA', f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
    _write(info / 'RECORD', record)
    for file_name, text in (extra or {}).items():
        _write(info / file_name, text)


@pytest.mark.medium
@pytest.mark.usefixtures('isolated_modules')
class DescribeOperatorOwnershipInstallRecord:
    def it_misses_for_a_source_checkout_module_with_a_leftover_egg_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sibling checkout on sys.path with a stale ``src/<pkg>.egg-info`` (legacy develop, or a build leftover).

        No PEP 610 marker and the file is a working-tree source file, so editing it does not change the version.
        """
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        src = tmp_path / 'sibling' / 'src'
        _write(src / 'sibpkg_r7' / '__init__.py', '')
        _write(src / 'sibpkg_r7' / 'ops.py', OPERATOR_SOURCE)
        _write(src / 'sibpkg_r7.egg-info' / 'PKG-INFO', 'Metadata-Version: 2.1\nName: sibpkg-r7\nVersion: 0.1\n')
        _write(src / 'sibpkg_r7.egg-info' / 'top_level.txt', 'sibpkg_r7\n')
        monkeypatch.syspath_prepend(str(src))
        operator = importlib.import_module('sibpkg_r7.ops').HelperOperator()

        assert installed_versions_fingerprint([operator], rootdir) != installed_versions_fingerprint(
            [operator], rootdir
        )

    def it_misses_for_a_namespace_file_no_distribution_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``nsr7/orphan/ops.py`` is in no RECORD, yet it inherits the label of the dist that owns ``nsr7/a``."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        site = tmp_path / 'site'
        _write(site / 'nsr7' / 'a' / '__init__.py', '')
        _write(site / 'nsr7' / 'orphan' / '__init__.py', '')
        _write(site / 'nsr7' / 'orphan' / 'ops.py', OPERATOR_SOURCE)
        _dist_info(site, 'nsr7-a', '1.0', 'nsr7/a/__init__.py,,\n')
        monkeypatch.syspath_prepend(str(site))
        operator = importlib.import_module('nsr7.orphan.ops').HelperOperator()

        assert 'nsr7-a==1.0' not in installed_versions_fingerprint([operator], rootdir)

    def it_misses_for_a_helper_outside_the_package_of_an_editable_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monorepo: the workspace root is installed editable, pytest's rootdir is a member directory.

        ``tools/helper_r7.py`` sits under the editable project directory but is not part of the distribution
        (its top-level module is not ``edpkg_r7``), so it must not take ``edpkg-r7``'s version as its key.
        """
        workspace = tmp_path / 'workspace'
        rootdir = workspace / 'member'
        rootdir.mkdir(parents=True)
        _write(workspace / 'src' / 'edpkg_r7' / '__init__.py', '')
        _write(workspace / 'tools' / 'helper_r7.py', OPERATOR_SOURCE)
        site = tmp_path / 'site'
        direct_url = json.dumps({'url': workspace.as_uri(), 'dir_info': {'editable': True}})
        _dist_info(site, 'edpkg-r7', '3.0', '', {'direct_url.json': direct_url, 'top_level.txt': 'edpkg_r7\n'})
        monkeypatch.syspath_prepend(str(site))
        monkeypatch.syspath_prepend(str(workspace / 'tools'))
        operator = importlib.import_module('helper_r7').HelperOperator()

        assert 'edpkg-r7==3.0' not in installed_versions_fingerprint([operator], rootdir)


def _load_conftest_operator(conftest: Path) -> object:
    """Import ``conftest`` the way pytest does: under a unique module name, from its file path."""
    spec = importlib.util.spec_from_file_location(f'conftest_r890_{conftest.parent.name}', conftest)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.HelperOperator()


@pytest.mark.medium
@pytest.mark.usefixtures('isolated_modules')
class DescribeConftestOperatorOwnership:
    def it_misses_for_a_conftest_operator_outside_the_rootdir(self, tmp_path: Path) -> None:
        """Only conftests from the rootdir down to a test file are hashed, so one above the rootdir is unhashed."""
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        _write(tmp_path / 'outside' / 'conftest.py', OPERATOR_SOURCE)
        operator = _load_conftest_operator(tmp_path / 'outside' / 'conftest.py')

        assert installed_versions_fingerprint([operator], rootdir) != installed_versions_fingerprint(
            [operator], rootdir
        )

    def it_keeps_a_stable_key_for_a_conftest_operator_inside_the_rootdir(self, tmp_path: Path) -> None:
        rootdir = tmp_path / 'project'
        _write(rootdir / 'conftest.py', OPERATOR_SOURCE)
        operator = _load_conftest_operator(rootdir / 'conftest.py')

        assert installed_versions_fingerprint([operator], rootdir) == installed_versions_fingerprint(
            [operator], rootdir
        )
