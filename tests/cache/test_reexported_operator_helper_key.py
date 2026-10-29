"""The cache key follows the file that defines an operator helper, not a package that re-exports it (#882)."""

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


def _fresh_import(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.delitem(sys.modules, 'gremlin_pkg', raising=False)
    monkeypatch.delitem(sys.modules, 'gremlin_pkg._impl', raising=False)
    return importlib.import_module('gremlin_pkg').HelperOperator()


@pytest.mark.medium
class DescribeReexportedOperatorHelper:
    def it_changes_the_key_when_the_defining_file_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / 'project'
        package = root / 'gremlin_pkg'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text(PACKAGE_INIT)
        (package / '_impl.py').write_text(IMPL_V1)
        monkeypatch.syspath_prepend(str(root))
        before = installed_versions_fingerprint([_fresh_import(monkeypatch)], root)
        (package / '_impl.py').write_text(IMPL_V2)
        importlib.invalidate_caches()

        after = installed_versions_fingerprint([_fresh_import(monkeypatch)], root)

        assert before != after
