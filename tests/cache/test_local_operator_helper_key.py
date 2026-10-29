"""A project-local operator helper module makes every run miss the cache (#882).

Hashing helper files was dropped: a project-local helper gets the always-miss token. Slower, never stale.
Restoring hits is tracked in #887.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR_SOURCE = 'class HelperOperator:\n    name = "helper"\n    description = "x"\n    delta = {delta}\n'


def _load_operator(
    monkeypatch: pytest.MonkeyPatch, path: Path, module_name: str = 'helper_mod', source: str | None = None
) -> object:
    if source is not None:
        path.write_text(source)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module.HelperOperator()


@pytest.mark.medium
class DescribeLocalOperatorHelperInFingerprint:
    def it_changes_when_the_helper_module_content_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        helper = tmp_path / 'helper_mod.py'
        before = _load_operator(monkeypatch, helper, source=OPERATOR_SOURCE.format(delta=1))
        fingerprint_before = installed_versions_fingerprint([before], tmp_path)

        after = _load_operator(monkeypatch, helper, source=OPERATOR_SOURCE.format(delta=0))

        assert installed_versions_fingerprint([after], tmp_path) != fingerprint_before

    def it_misses_the_cache_even_when_the_helper_module_is_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _load_operator(monkeypatch, tmp_path / 'helper_mod.py', source=OPERATOR_SOURCE.format(delta=1))

        assert installed_versions_fingerprint([operator], tmp_path) != installed_versions_fingerprint(
            [operator], tmp_path
        )

    def it_contributes_the_always_miss_token_for_the_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _load_operator(monkeypatch, tmp_path / 'helper_mod.py', source=OPERATOR_SOURCE.format(delta=1))

        assert 'local-operator=helper_mod:unreadable-' in installed_versions_fingerprint([operator], tmp_path)

    def it_adds_nothing_for_an_operator_defined_in_a_conftest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conftest = tmp_path / 'conftest.py'
        before = _load_operator(monkeypatch, conftest, 'conftest_mod', OPERATOR_SOURCE.format(delta=1))
        fingerprint_before = installed_versions_fingerprint([before], tmp_path)

        after = _load_operator(monkeypatch, conftest, 'conftest_mod', OPERATOR_SOURCE.format(delta=0))

        assert installed_versions_fingerprint([after], tmp_path) == fingerprint_before

    def it_adds_nothing_for_a_built_in_operator(self, tmp_path: Path) -> None:
        assert installed_versions_fingerprint([ComparisonOperator()], tmp_path) == installed_versions_fingerprint(
            [], tmp_path
        )

    def it_adds_nothing_for_a_helper_outside_the_rootdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / 'root'
        root.mkdir()
        operator = _load_operator(monkeypatch, tmp_path / 'helper_mod.py', source=OPERATOR_SOURCE.format(delta=1))

        assert 'local-operator=' not in installed_versions_fingerprint([operator], root)

    def it_misses_the_cache_when_the_module_has_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        operator = _load_operator(monkeypatch, tmp_path / 'helper_mod.py', source=OPERATOR_SOURCE.format(delta=1))
        monkeypatch.delattr(sys.modules['helper_mod'], '__file__')

        first = installed_versions_fingerprint([operator], tmp_path)
        second = installed_versions_fingerprint([operator], tmp_path)

        assert first != second

    def it_misses_the_cache_when_the_module_file_is_unreadable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        helper = tmp_path / 'helper_mod.py'
        operator = _load_operator(monkeypatch, helper, source=OPERATOR_SOURCE.format(delta=1))
        helper.unlink()

        first = installed_versions_fingerprint([operator], tmp_path)
        second = installed_versions_fingerprint([operator], tmp_path)

        assert first != second
