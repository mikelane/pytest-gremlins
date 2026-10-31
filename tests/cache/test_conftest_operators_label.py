"""The versions fingerprint hashes every loaded conftest.py once an operator is defined in one (#899)."""

from __future__ import annotations

import importlib
import shutil
import sys
import types
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.operators.protocol import GremlinOperator

LABEL_PREFIX = 'conftest-operators='
OPERATOR_SOURCE = (
    'class Local:\n    name = "local"\n    description = "x"\n\n    def mutate(self, node):\n        return []\n'
)


def _operator_in_module(
    monkeypatch: pytest.MonkeyPatch, module_name: str, module_file: Path, source: str = OPERATOR_SOURCE
) -> object:
    module = types.ModuleType(module_name)
    module.__file__ = str(module_file)
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(source, str(module_file), 'exec'), module.__dict__)  # noqa: S102
    return module.Local()


def _operator_borrowing_conftest_function(monkeypatch: pytest.MonkeyPatch, conftest: Path) -> object:
    module = types.ModuleType('helper_module')
    monkeypatch.setitem(sys.modules, 'helper_module', module)
    borrowed = compile('def mutate(self, node):\n    return []\n', str(conftest), 'exec')
    scope: dict[str, object] = {}
    exec(borrowed, scope)  # noqa: S102
    exec(  # noqa: S102
        compile('class Local:\n    name = "local"\n    description = "x"\n', '/virtual/helper_module.py', 'exec'),
        module.__dict__,
    )
    module.Local.mutate = scope['mutate']
    return module.Local()


def _label(fingerprint: str) -> str:
    return next(part for part in fingerprint.split('|') if part.startswith(LABEL_PREFIX))


@pytest.fixture
def conftests(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / 'conftest.py'
    nested = tmp_path / 'a' / 'conftest.py'
    nested.parent.mkdir()
    root.write_text('ROOT = 1\n')
    nested.write_text('NESTED = 1\n')
    return root, nested


@pytest.mark.medium
class DescribeConftestOperatorsLabel:
    def it_leaves_the_fingerprint_untouched_when_no_operator_is_defined_in_a_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path
    ) -> None:
        operators: list[GremlinOperator] = [ComparisonOperator()]

        with_conftests = installed_versions_fingerprint(operators, tmp_path, conftests)

        assert with_conftests == installed_versions_fingerprint(operators, tmp_path)

    def it_adds_one_label_when_an_operator_module_is_named_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert fingerprint.count(LABEL_PREFIX) == 1

    def it_adds_the_label_when_an_operator_module_ends_in_dot_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'pkg.conftest', conftests[0])

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert LABEL_PREFIX in fingerprint

    def it_adds_the_label_when_a_function_in_the_class_body_comes_from_a_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_borrowing_conftest_function(monkeypatch, conftests[0])

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert LABEL_PREFIX in fingerprint

    def it_changes_when_any_loaded_conftest_changes(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])
        before = _label(installed_versions_fingerprint([operator], tmp_path, conftests))

        conftests[1].write_text('NESTED = 2\n')

        assert _label(installed_versions_fingerprint([operator], tmp_path, conftests)) != before

    def it_is_stable_when_nothing_changes_and_the_order_differs(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])
        forward = _label(installed_versions_fingerprint([operator], tmp_path, conftests))

        backward = _label(installed_versions_fingerprint([operator], tmp_path, conftests[::-1]))

        assert forward == backward

    def it_changes_when_a_conftest_is_renamed(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])
        before = _label(installed_versions_fingerprint([operator], tmp_path, conftests))
        moved = tmp_path / 'b' / 'conftest.py'
        moved.parent.mkdir()
        conftests[1].rename(moved)

        after = _label(installed_versions_fingerprint([operator], tmp_path, [conftests[0], moved]))

        assert after != before

    def it_names_a_conftest_outside_the_rootdir_by_its_absolute_path(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])
        elsewhere = tmp_path / 'elsewhere'
        elsewhere.mkdir()

        inside = _label(installed_versions_fingerprint([operator], tmp_path, [conftests[0]]))
        outside = _label(installed_versions_fingerprint([operator], elsewhere, [conftests[0]]))

        assert inside != outside

    def it_always_misses_when_a_loaded_conftest_cannot_be_read(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest', conftests[0])
        conftests[1].unlink()

        first = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert first != installed_versions_fingerprint([operator], tmp_path, conftests)


def _write_installed_conftest_operator(site: Path, version: str) -> None:
    files = {
        site / 'instpkg_r3' / '__init__.py': '',
        site / 'instpkg_r3' / 'conftest.py': 'class Op:\n    name = "op"\n    description = "x"\n',
        site / f'instpkg_r3-{version}.dist-info' / 'METADATA': (
            f'Metadata-Version: 2.1\nName: instpkg-r3\nVersion: {version}\n'
        ),
        site / f'instpkg_r3-{version}.dist-info' / 'RECORD': 'instpkg_r3/__init__.py,,\ninstpkg_r3/conftest.py,,\n',
        site / f'instpkg_r3-{version}.dist-info' / 'top_level.txt': 'instpkg_r3\n',
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


@pytest.fixture
def rootdir(tmp_path: Path) -> Path:
    project = tmp_path / 'project'
    project.mkdir()
    return project


@pytest.fixture
def installed_conftest_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    site = tmp_path / 'site'
    _write_installed_conftest_operator(site, '1.0')
    monkeypatch.syspath_prepend(str(site))
    for name in ('instpkg_r3', 'instpkg_r3.conftest'):
        monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.invalidate_caches()
    operator = importlib.import_module('instpkg_r3.conftest').Op()
    yield operator
    for name in ('instpkg_r3', 'instpkg_r3.conftest'):
        sys.modules.pop(name, None)


@pytest.mark.medium
class DescribeInstalledPackageWithConftestNamedOperatorModule:
    def it_keys_on_the_version_of_the_owning_distribution(
        self, installed_conftest_operator: object, rootdir: Path
    ) -> None:
        fingerprint = installed_versions_fingerprint([installed_conftest_operator], rootdir, loaded_conftests=[])

        assert 'instpkg-r3==1.0' in fingerprint

    def it_adds_no_conftest_label(self, installed_conftest_operator: object, rootdir: Path) -> None:
        fingerprint = installed_versions_fingerprint([installed_conftest_operator], rootdir, loaded_conftests=[])

        assert LABEL_PREFIX not in fingerprint

    def it_changes_when_the_package_is_upgraded(
        self, installed_conftest_operator: object, rootdir: Path, tmp_path: Path
    ) -> None:
        before = installed_versions_fingerprint([installed_conftest_operator], rootdir, loaded_conftests=[])
        site = tmp_path / 'site'
        shutil.rmtree(site / 'instpkg_r3-1.0.dist-info')
        _write_installed_conftest_operator(site, '2.0')

        after = installed_versions_fingerprint([installed_conftest_operator], rootdir, loaded_conftests=[])

        assert after != before
