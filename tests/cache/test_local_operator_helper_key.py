"""A project-local operator helper module makes every run miss the cache (#882).

Hashing helper files was dropped: a project-local helper gets the always-miss token. Slower, never stale.
Restoring hits is tracked in #887.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

import pluggy
import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint
from pytest_gremlins.operators.comparison import ComparisonOperator

OPERATOR_SOURCE = (
    'class HelperOperator:\n    name = "helper"\n    description = "x"\n    delta = {delta}\n\n'
    '    def mutate(self, node):\n        return []\n'
)


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

    def it_misses_the_cache_for_a_registered_helper_outside_the_rootdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / 'root'
        root.mkdir()
        operator = _load_operator(monkeypatch, tmp_path / 'helper_mod.py', source=OPERATOR_SOURCE.format(delta=1))

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)

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


def _always_misses(operator: object, root: Path) -> bool:
    return installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)


@pytest.mark.medium
class DescribeHelperClassification:
    """A class keeps a stable key only if it is importable by qualified name AND an installed distribution owns it."""

    def it_misses_for_a_path_loaded_helper_whose_spec_name_is_a_stdlib_module(self, tmp_path: Path) -> None:
        root = tmp_path / 'project'
        root.mkdir()
        operator = _load_operator_unregistered(root / 'gremlin_ops.py', module_name='json')

        assert _always_misses(operator, root)

    def it_misses_for_a_path_loaded_helper_whose_spec_name_is_an_installed_dist_module(self, tmp_path: Path) -> None:
        root = tmp_path / 'project'
        root.mkdir()
        operator = _load_operator_unregistered(root / 'gremlin_ops.py', module_name='pluggy')

        assert _always_misses(operator, root)

    def it_misses_for_an_importable_helper_outside_the_rootdir_that_no_distribution_installs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / 'project'
        shared = tmp_path / 'shared'
        root.mkdir()
        shared.mkdir()
        (shared / 'shared_ops.py').write_text(OPERATOR_SOURCE.format(delta=1))
        monkeypatch.syspath_prepend(str(shared))
        monkeypatch.delitem(sys.modules, 'shared_ops', raising=False)
        operator = importlib.import_module('shared_ops').HelperOperator()

        assert _always_misses(operator, root)

    def it_misses_for_a_namespace_package_module(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / 'project'
        (root / 'ns_pkg').mkdir(parents=True)
        monkeypatch.syspath_prepend(str(root))
        monkeypatch.delitem(sys.modules, 'ns_pkg', raising=False)
        importlib.import_module('ns_pkg')
        operator = type('HelperOperator', (), {'__module__': 'ns_pkg'})()

        assert _always_misses(operator, root)

    def it_misses_for_a_class_registered_under_an_installed_package_name_whose_file_is_elsewhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        elsewhere = tmp_path / 'elsewhere'
        elsewhere.mkdir()
        source = elsewhere / 'fake_ops.py'
        source.write_text(OPERATOR_SOURCE.format(delta=1))
        spec = importlib.util.spec_from_file_location('pluggy.fake_ops', source)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, 'pluggy.fake_ops', module)
        spec.loader.exec_module(module)
        operator = module.HelperOperator()
        operator_class = type(operator)
        operator_class.__module__ = 'pluggy.fake_ops'

        assert _always_misses(operator, tmp_path / 'project')
        assert 'pluggy==' not in installed_versions_fingerprint([operator], tmp_path / 'project')

    def it_keeps_a_stable_key_for_an_installed_distribution_under_a_venv_in_the_rootdir(self) -> None:
        directory_holding_the_venv = Path(sys.prefix).resolve().parent
        operator = pluggy.HookimplMarker('project')

        assert not _always_misses(operator, directory_holding_the_venv)


def _load_operator_unregistered(path: Path, module_name: str) -> object:
    path.write_text(OPERATOR_SOURCE.format(delta=1))
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HelperOperator()
