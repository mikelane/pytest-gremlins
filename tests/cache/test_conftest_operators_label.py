"""The versions fingerprint hashes every loaded conftest.py once an operator is defined in one (#899)."""

from __future__ import annotations

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


def _operator_in_module(monkeypatch: pytest.MonkeyPatch, module_name: str, source: str = OPERATOR_SOURCE) -> object:
    module = types.ModuleType(module_name)
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(source, f'/virtual/{module_name}.py', 'exec'), module.__dict__)  # noqa: S102
    return module.Local()


def _operator_borrowing_conftest_function(monkeypatch: pytest.MonkeyPatch) -> object:
    module = types.ModuleType('helper_module')
    monkeypatch.setitem(sys.modules, 'helper_module', module)
    borrowed = compile('def mutate(self, node):\n    return []\n', '/virtual/conftest.py', 'exec')
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
        operator = _operator_in_module(monkeypatch, 'conftest')

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert fingerprint.count(LABEL_PREFIX) == 1

    def it_adds_the_label_when_an_operator_module_ends_in_dot_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'pkg.conftest')

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert LABEL_PREFIX in fingerprint

    def it_adds_the_label_when_a_function_in_the_class_body_comes_from_a_conftest(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_borrowing_conftest_function(monkeypatch)

        fingerprint = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert LABEL_PREFIX in fingerprint

    def it_changes_when_any_loaded_conftest_changes(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest')
        before = _label(installed_versions_fingerprint([operator], tmp_path, conftests))

        conftests[1].write_text('NESTED = 2\n')

        assert _label(installed_versions_fingerprint([operator], tmp_path, conftests)) != before

    def it_is_stable_when_nothing_changes_and_the_order_differs(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest')
        forward = _label(installed_versions_fingerprint([operator], tmp_path, conftests))

        backward = _label(installed_versions_fingerprint([operator], tmp_path, conftests[::-1]))

        assert forward == backward

    def it_changes_when_a_conftest_is_renamed(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest')
        before = _label(installed_versions_fingerprint([operator], tmp_path, conftests))
        moved = tmp_path / 'b' / 'conftest.py'
        moved.parent.mkdir()
        conftests[1].rename(moved)

        after = _label(installed_versions_fingerprint([operator], tmp_path, [conftests[0], moved]))

        assert after != before

    def it_names_a_conftest_outside_the_rootdir_by_its_absolute_path(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest')
        elsewhere = tmp_path / 'elsewhere'
        elsewhere.mkdir()

        inside = _label(installed_versions_fingerprint([operator], tmp_path, [conftests[0]]))
        outside = _label(installed_versions_fingerprint([operator], elsewhere, [conftests[0]]))

        assert inside != outside

    def it_always_misses_when_a_loaded_conftest_cannot_be_read(
        self, conftests: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_in_module(monkeypatch, 'conftest')
        conftests[1].unlink()

        first = installed_versions_fingerprint([operator], tmp_path, conftests)

        assert first != installed_versions_fingerprint([operator], tmp_path, conftests)
