"""Edge cases of the conftest-operators import walk: deep modules, parent packages, symlinks (#924)."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.operators.protocol import GremlinOperator

LABEL_PREFIX = 'conftest-operators='
OPERATOR_SOURCE = (
    'class Local:\n    name = "local"\n    description = "x"\n\n    def mutate(self, node):\n        return []\n'
)
TOO_DEEP_SOURCES = {
    'parser-stack-overflow': 'x = ' + '-' * 20000 + '1\n',
    'compiler-recursion': 'x = y' + '.a' * 100000 + '\n',
}


def _label(fingerprint: str) -> str:
    return next(part for part in fingerprint.split('|') if part.startswith(LABEL_PREFIX))


def _load(monkeypatch: pytest.MonkeyPatch, name: str, file: Path) -> None:
    module = types.ModuleType(name)
    module.__file__ = str(file)
    monkeypatch.setitem(sys.modules, name, module)


def _operator_from(conftest: Path, module_name: str, monkeypatch: pytest.MonkeyPatch) -> GremlinOperator:
    module = types.ModuleType(module_name)
    module.__file__ = str(conftest)
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(OPERATOR_SOURCE, str(conftest), 'exec'), module.__dict__)  # noqa: S102
    local: GremlinOperator = module.Local()
    return local


@pytest.mark.medium
class DescribeConftestImportWalkEdgeCases:
    @pytest.mark.parametrize('deep_source', list(TOO_DEEP_SOURCES.values()), ids=list(TOO_DEEP_SOURCES))
    def it_always_misses_instead_of_crashing_on_a_module_too_deep_to_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deep_source: str
    ) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('def _later():\n    from . import _generated\n')
        (tmp_path / '_generated.py').write_text(deep_source)
        operator = _operator_from(conftest, 'conftest', monkeypatch)

        first = installed_versions_fingerprint([operator], tmp_path, [conftest])

        assert first != installed_versions_fingerprint([operator], tmp_path, [conftest])

    def it_changes_the_label_when_the_package_init_a_dotted_import_binds_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = tmp_path / 'pkg'
        package.mkdir()
        init = package / '__init__.py'
        init.write_text('OFFSET = 1\n')
        helpers = package / 'helpers.py'
        helpers.write_text('')
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('import pkg.helpers\n\nSHIFT = pkg.OFFSET\n')
        _load(monkeypatch, 'pkg', init)
        _load(monkeypatch, 'pkg.helpers', helpers)
        operator = _operator_from(conftest, 'conftest', monkeypatch)
        before = _label(installed_versions_fingerprint([operator], tmp_path, [conftest]))

        init.write_text('OFFSET = 2\n')

        assert _label(installed_versions_fingerprint([operator], tmp_path, [conftest])) != before

    def it_keeps_the_label_when_a_module_named_like_the_package_directory_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package = tmp_path / 'a'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / 'helper.py').write_text('OFFSET = 1\n')
        conftest = package / 'conftest.py'
        conftest.write_text('from . import helper\n')
        unrelated = tmp_path / 'a.py'
        unrelated.write_text('UNRELATED = 1\n')
        operator = _operator_from(conftest, 'a.conftest', monkeypatch)
        before = _label(installed_versions_fingerprint([operator], tmp_path, [conftest]))

        unrelated.write_text('UNRELATED = 2\n')

        assert _label(installed_versions_fingerprint([operator], tmp_path, [conftest])) == before

    def it_changes_the_label_when_a_symlinked_helper_under_the_rootdir_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        shared = tmp_path / 'shared'
        shared.mkdir()
        target = shared / '_helper.py'
        target.write_text('OFFSET = 1\n')
        link = rootdir / '_helper.py'
        link.symlink_to(target)
        conftest = rootdir / 'conftest.py'
        conftest.write_text('import _helper\n')
        _load(monkeypatch, '_helper', link)
        operator = _operator_from(conftest, 'conftest', monkeypatch)
        before = _label(installed_versions_fingerprint([operator], rootdir, [conftest]))

        target.write_text('OFFSET = 2\n')

        assert _label(installed_versions_fingerprint([operator], rootdir, [conftest])) != before
