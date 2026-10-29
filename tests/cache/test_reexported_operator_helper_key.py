"""The cache key follows the file that defines an operator helper, not a package that re-exports it (#882).

The module file is trusted only when it holds a ``class`` statement at the path given by the class's ``__qualname__``.
Otherwise the helper gets the always-miss token, so an edit to the real defining file is never served stale.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

IMPL_V1 = 'class HelperOperator:\n    name = "helper"\n    description = "v1"\n'
IMPL_V2 = 'class HelperOperator:\n    name = "helper"\n    description = "v2 edited"\n'
PACKAGE_INIT = 'from gremlin_pkg._impl import HelperOperator\n\nHelperOperator.__module__ = "gremlin_pkg"\n'
DEFINING_INIT_V1 = 'class HelperOperator:\n    name = "helper"\n    description = "v1"\n'
DEFINING_INIT_V2 = 'class HelperOperator:\n    name = "helper"\n    description = "v2 edited"\n'
NESTED_INIT_V1 = 'class Outer:\n    class HelperOperator:\n        name = "helper"\n        description = "v1"\n'
NESTED_INIT_V2 = 'class Outer:\n    class HelperOperator:\n        name = "helper"\n        description = "v2 edited"\n'
IF_BLOCK_INIT_V1 = 'if True:\n    class HelperOperator:\n        name = "helper"\n        description = "v1"\n'
IF_BLOCK_INIT_V2 = 'if True:\n    class HelperOperator:\n        name = "helper"\n        description = "v2 edited"\n'
TRY_BLOCK_INIT_V1 = (
    'try:\n'
    '    class HelperOperator:\n'
    '        name = "helper"\n'
    '        description = "v1"\n'
    'except ImportError:\n'
    '    pass\n'
)
TRY_BLOCK_INIT_V2 = (
    'try:\n'
    '    class HelperOperator:\n'
    '        name = "helper"\n'
    '        description = "v2 edited"\n'
    'except ImportError:\n'
    '    pass\n'
)
UNPARSEABLE = 'def broken(:\n'


def _import_helper(monkeypatch: pytest.MonkeyPatch, qualname: str = 'HelperOperator') -> object:
    monkeypatch.delitem(sys.modules, 'gremlin_pkg', raising=False)
    monkeypatch.delitem(sys.modules, 'gremlin_pkg._impl', raising=False)
    importlib.invalidate_caches()
    holder: object = importlib.import_module('gremlin_pkg')
    for part in qualname.split('.'):
        holder = getattr(holder, part)
    return holder()


def _make_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, init_source: str) -> tuple[Path, Path]:
    root = tmp_path / 'project'
    package = root / 'gremlin_pkg'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(init_source)
    monkeypatch.syspath_prepend(str(root))
    return root, package


@pytest.mark.medium
class DescribeReexportedOperatorHelper:
    def it_changes_the_key_when_the_defining_file_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, package = _make_package(tmp_path, monkeypatch, PACKAGE_INIT)
        (package / '_impl.py').write_text(IMPL_V1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch)], root)
        (package / '_impl.py').write_text(IMPL_V2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch)], root)

        assert before != after


@pytest.mark.medium
class DescribeInitModuleThatDefinesTheClass:
    def it_keeps_the_key_while_the_file_is_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, _ = _make_package(tmp_path, monkeypatch, DEFINING_INIT_V1)
        operator = _import_helper(monkeypatch)

        assert installed_versions_fingerprint([operator], root) == installed_versions_fingerprint([operator], root)

    def it_changes_the_key_when_the_init_file_is_edited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, DEFINING_INIT_V1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch)], root)
        (package / '__init__.py').write_text(DEFINING_INIT_V2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch)], root)

        assert before != after


@pytest.mark.medium
class DescribeClassNestedInAnotherClass:
    def it_keeps_the_key_while_the_file_is_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, _ = _make_package(tmp_path, monkeypatch, NESTED_INIT_V1)
        operator = _import_helper(monkeypatch, 'Outer.HelperOperator')

        assert installed_versions_fingerprint([operator], root) == installed_versions_fingerprint([operator], root)

    def it_changes_the_key_when_the_file_is_edited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, NESTED_INIT_V1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch, 'Outer.HelperOperator')], root)
        (package / '__init__.py').write_text(NESTED_INIT_V2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch, 'Outer.HelperOperator')], root)

        assert before != after


@pytest.mark.medium
class DescribeClassDefinedInsideAnIfBlock:
    def it_keeps_the_key_while_the_file_is_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, _ = _make_package(tmp_path, monkeypatch, IF_BLOCK_INIT_V1)
        operator = _import_helper(monkeypatch)

        assert installed_versions_fingerprint([operator], root) == installed_versions_fingerprint([operator], root)

    def it_changes_the_key_when_the_file_is_edited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, IF_BLOCK_INIT_V1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch)], root)
        (package / '__init__.py').write_text(IF_BLOCK_INIT_V2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch)], root)

        assert before != after


@pytest.mark.medium
class DescribeClassDefinedInsideATryBlock:
    def it_keeps_the_key_while_the_file_is_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, _ = _make_package(tmp_path, monkeypatch, TRY_BLOCK_INIT_V1)
        operator = _import_helper(monkeypatch)

        assert installed_versions_fingerprint([operator], root) == installed_versions_fingerprint([operator], root)

    def it_changes_the_key_when_the_file_is_edited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, TRY_BLOCK_INIT_V1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch)], root)
        (package / '__init__.py').write_text(TRY_BLOCK_INIT_V2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch)], root)

        assert before != after


@pytest.mark.medium
class DescribeModuleFileThatCannotBeChecked:
    def it_always_misses_when_the_file_no_longer_parses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, DEFINING_INIT_V1)
        operator = _import_helper(monkeypatch)
        (package / '__init__.py').write_text(UNPARSEABLE)

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)

    def it_always_misses_when_the_file_is_unreadable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, DEFINING_INIT_V1)
        operator = _import_helper(monkeypatch)
        (package / '__init__.py').unlink()

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)
