"""Adversarial QA run 2 probes for the conftest-operators import walk (#924)."""

from __future__ import annotations

import sys
import time
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


def _lbl(op: GremlinOperator, root: Path, conftest: Path) -> str:
    return _label(installed_versions_fingerprint([op], root, [conftest]))


@pytest.mark.medium
class DescribeRelativeImportsInConftestOperatorLabel:
    def it_changes_the_label_when_the_init_of_an_intermediate_package_of_a_relative_dotted_import_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pkg = tmp_path / 'pkg'
        (pkg / 'sub').mkdir(parents=True)
        (pkg / '__init__.py').write_text('')
        sub_init = pkg / 'sub' / '__init__.py'
        sub_init.write_text('OFFSET = 1\n')
        (pkg / 'sub' / 'deep.py').write_text('')
        conftest = pkg / 'conftest.py'
        conftest.write_text('from .sub.deep import z\n')
        op = _operator_from(conftest, 'pkg.conftest', monkeypatch)
        before = _lbl(op, tmp_path, conftest)

        sub_init.write_text('OFFSET = 2\n')

        assert _lbl(op, tmp_path, conftest) != before

    def it_changes_the_label_when_the_init_of_an_absolute_from_import_parent_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pkg = tmp_path / 'pkg'
        (pkg / 'sub').mkdir(parents=True)
        init = pkg / '__init__.py'
        init.write_text('A = 1\n')
        sub_init = pkg / 'sub' / '__init__.py'
        sub_init.write_text('B = 1\n')
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from pkg.sub import y\n')
        _load(monkeypatch, 'pkg', init)
        _load(monkeypatch, 'pkg.sub', sub_init)
        op = _operator_from(conftest, 'conftest', monkeypatch)
        before = _lbl(op, tmp_path, conftest)
        init.write_text('A = 2\n')
        mid = _lbl(op, tmp_path, conftest)
        sub_init.write_text('B = 2\n')

        assert mid != before
        assert _lbl(op, tmp_path, conftest) != mid

    def it_does_not_crash_on_a_symlink_loop_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import loop\nimport loop2\n')
        (tmp_path / 'loop.py').symlink_to(tmp_path / 'loop.py')
        (tmp_path / 'loop2.py').symlink_to(tmp_path / 'loop2.py')
        _load(monkeypatch, 'loop2', tmp_path / 'loop2.py')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        installed_versions_fingerprint([op], tmp_path, [conftest])

    def it_does_not_crash_when_resolving_a_symlink_loop_raises_runtime_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import helper\n')
        (tmp_path / 'helper.py').write_text('A = 1\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)
        path_type = type(tmp_path)
        original_resolve = path_type.resolve

        def resolve_like_python_312(self: Path, strict: bool = False) -> Path:
            if self.name == 'helper.py':
                raise RuntimeError(f'Symlink loop from {str(self)!r}')
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(path_type, 'resolve', resolve_like_python_312)

        installed_versions_fingerprint([op], tmp_path, [conftest])

    def it_does_not_crash_on_a_relative_import_beyond_the_filesystem_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from ' + '.' * 200 + ' import x\nfrom ' + '.' * 200 + 'a.b import y\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        installed_versions_fingerprint([op], tmp_path, [conftest])

    def it_always_misses_on_a_null_byte_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import h\n')
        (tmp_path / 'h.py').write_bytes(b'x = 1\x00\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        assert installed_versions_fingerprint([op], tmp_path, [conftest]) != installed_versions_fingerprint(
            [op], tmp_path, [conftest]
        )

    def it_always_misses_on_a_non_utf8_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import h\n')
        (tmp_path / 'h.py').write_bytes(b'x = "\xff\xfe"\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        assert installed_versions_fingerprint([op], tmp_path, [conftest]) != installed_versions_fingerprint(
            [op], tmp_path, [conftest]
        )

    def it_terminates_on_import_cycles(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / 'a.py').write_text('from . import b\n')
        (tmp_path / 'b.py').write_text('from . import a\nfrom . import conftest\n')
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import a\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        assert _lbl(op, tmp_path, conftest) == _lbl(op, tmp_path, conftest)

    def it_stays_fast_on_a_long_chain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        count = 1500
        for i in range(count):
            nxt = f'from . import m{i + 1}\n' if i + 1 < count else ''
            (tmp_path / f'm{i}.py').write_text(nxt + f'V = {i}\n')
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import m0\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)

        start = time.perf_counter()
        _lbl(op, tmp_path, conftest)

        assert time.perf_counter() - start < 3

    def it_ignores_an_unrelated_file_edit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / 'h.py').write_text('V = 1\n')
        other = tmp_path / 'other.py'
        other.write_text('V = 1\n')
        conftest = tmp_path / 'conftest.py'
        conftest.write_text('from . import h\n')
        op = _operator_from(conftest, 'conftest', monkeypatch)
        before = _lbl(op, tmp_path, conftest)

        other.write_text('V = 2\n')

        assert _lbl(op, tmp_path, conftest) == before

    def it_hashes_a_helper_when_the_rootdir_is_a_symlink(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        real = tmp_path / 'real'
        real.mkdir()
        link = tmp_path / 'link'
        link.symlink_to(real)
        helper = real / 'h.py'
        helper.write_text('V = 1\n')
        conftest = link / 'conftest.py'
        conftest.write_text('import h\n')
        _load(monkeypatch, 'h', link / 'h.py')
        op = _operator_from(conftest, 'conftest', monkeypatch)
        before = _lbl(op, link, conftest)

        helper.write_text('V = 2\n')

        assert _lbl(op, link, conftest) != before
