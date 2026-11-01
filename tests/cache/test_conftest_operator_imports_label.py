"""The conftest-operators label folds in the local modules the conftests import (#924)."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

LABEL_PREFIX = 'conftest-operators='
OPERATOR_SOURCE = (
    'class Local:\n    name = "local"\n    description = "x"\n\n    def mutate(self, node):\n        return []\n'
)


def _label(fingerprint: str) -> str:
    return next(part for part in fingerprint.split('|') if part.startswith(LABEL_PREFIX))


def _load(monkeypatch: pytest.MonkeyPatch, name: str, file: Path) -> None:
    module = types.ModuleType(name)
    module.__file__ = str(file)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    conftest = tmp_path / 'conftest.py'
    module = types.ModuleType('conftest')
    module.__file__ = str(conftest)
    monkeypatch.setitem(sys.modules, 'conftest', module)
    exec(compile(OPERATOR_SOURCE, str(conftest), 'exec'), module.__dict__)  # noqa: S102
    return module.Local()  # type: ignore[attr-defined]


def _fingerprint_label(operator: object, tmp_path: Path, project_root: Path | None = None) -> str:
    fingerprint = installed_versions_fingerprint([operator], project_root or tmp_path, [tmp_path / 'conftest.py'])  # type: ignore[list-item]
    return _label(fingerprint)


@pytest.mark.medium
class DescribeConftestImportsInLabel:
    def it_changes_the_label_when_an_imported_helper_is_edited(
        self, operator: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / 'conftest.py').write_text('import _helper\n')
        helper = tmp_path / '_helper.py'
        helper.write_text('OFFSET = 1\n')
        _load(monkeypatch, '_helper', helper)
        before = _fingerprint_label(operator, tmp_path)

        helper.write_text('OFFSET = 2\n')

        assert _fingerprint_label(operator, tmp_path) != before

    def it_follows_imports_transitively(
        self, operator: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / 'conftest.py').write_text('import _outer\n')
        outer = tmp_path / '_outer.py'
        outer.write_text('import _inner\n')
        inner = tmp_path / '_inner.py'
        inner.write_text('OFFSET = 1\n')
        _load(monkeypatch, '_outer', outer)
        _load(monkeypatch, '_inner', inner)
        before = _fingerprint_label(operator, tmp_path)

        inner.write_text('OFFSET = 2\n')

        assert _fingerprint_label(operator, tmp_path) != before

    def it_resolves_a_relative_import_from_the_conftest_directory(self, operator: object, tmp_path: Path) -> None:
        (tmp_path / 'conftest.py').write_text('from . import _sibling\n')
        sibling = tmp_path / '_sibling.py'
        sibling.write_text('OFFSET = 1\n')
        before = _fingerprint_label(operator, tmp_path)

        sibling.write_text('OFFSET = 2\n')

        assert _fingerprint_label(operator, tmp_path) != before

    def it_ignores_an_imported_module_outside_the_rootdir(
        self, operator: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rootdir = tmp_path / 'rootdir'
        rootdir.mkdir()
        (tmp_path / 'conftest.py').write_text('import _elsewhere\n')
        elsewhere = tmp_path / '_elsewhere.py'
        elsewhere.write_text('OFFSET = 1\n')
        _load(monkeypatch, '_elsewhere', elsewhere)
        before = _fingerprint_label(operator, tmp_path, rootdir)

        elsewhere.write_text('OFFSET = 2\n')

        assert _fingerprint_label(operator, tmp_path, rootdir) == before
