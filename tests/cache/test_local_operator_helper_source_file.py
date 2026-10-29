"""A path-loaded helper (#882) is hashed by the file that defines it, not by a file its members borrow code from.

A decorator wrapper or a generated dataclass method carries the code of another file. Editing the helper must still
change the fingerprint, or a stale verdict is reused.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

DECORATOR_MODULE = (
    'import functools\n'
    '\n'
    '\n'
    'def passthrough(func):\n'
    '    @functools.wraps(func)\n'
    '    def wrapper(*args, **kwargs):\n'
    '        return func(*args, **kwargs)\n'
    '    return wrapper\n'
)
DECORATED_HELPER = (
    'from helper_decorators import passthrough\n'
    '\n'
    '\n'
    'class HelperOperator:\n'
    '    name = "helper"\n'
    '    description = "x"\n'
    '\n'
    '    @passthrough\n'
    '    def can_mutate(self, node):\n'
    '        return {delta}\n'
)
DATACLASS_HELPER = (
    'import dataclasses\n'
    '\n'
    'from pytest_gremlins.operators.comparison import ComparisonOperator\n'
    '\n'
    '\n'
    '@dataclasses.dataclass\n'
    'class HelperOperator(ComparisonOperator):\n'
    '    delta: int = {delta}\n'
)

CLASSMETHOD_HELPER = (
    'class HelperOperator:\n'
    '    name = "helper"\n'
    '    description = "x"\n'
    '\n'
    '    @classmethod\n'
    '    def can_mutate(cls, node):\n'
    '        return {delta}\n'
)


def _path_load_operator(path: Path, source: str) -> object:
    path.write_text(source)
    spec = importlib.util.spec_from_file_location('path_loaded_helper', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HelperOperator()


@pytest.mark.medium
class DescribePathLoadedHelperWhoseFirstMethodCodeLivesElsewhere:
    def it_changes_when_a_helper_with_a_library_decorated_method_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        library = tmp_path / 'site'
        library.mkdir()
        (library / 'helper_decorators.py').write_text(DECORATOR_MODULE)
        monkeypatch.syspath_prepend(str(library))
        monkeypatch.delitem(sys.modules, 'helper_decorators', raising=False)
        root = tmp_path / 'project'
        root.mkdir()
        helper = root / 'gremlin_ops.py'
        before = installed_versions_fingerprint([_path_load_operator(helper, DECORATED_HELPER.format(delta=1))], root)

        after = installed_versions_fingerprint([_path_load_operator(helper, DECORATED_HELPER.format(delta=0))], root)

        assert after != before

    def it_changes_when_a_helper_with_a_project_local_decorator_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / 'local_decorators.py').write_text(DECORATOR_MODULE)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, 'local_decorators', raising=False)
        source = DECORATED_HELPER.replace('helper_decorators', 'local_decorators')
        helper = tmp_path / 'gremlin_ops.py'
        before = installed_versions_fingerprint([_path_load_operator(helper, source.format(delta=1))], tmp_path)

        after = installed_versions_fingerprint([_path_load_operator(helper, source.format(delta=0))], tmp_path)

        assert after != before

    def it_changes_when_a_fields_only_dataclass_helper_is_edited(self, tmp_path: Path) -> None:
        helper = tmp_path / 'gremlin_ops.py'
        before = installed_versions_fingerprint(
            [_path_load_operator(helper, DATACLASS_HELPER.format(delta=1))], tmp_path
        )

        after = installed_versions_fingerprint(
            [_path_load_operator(helper, DATACLASS_HELPER.format(delta=0))], tmp_path
        )

        assert after != before


@pytest.mark.medium
class DescribePathLoadedHelperWithOnlyDescriptorWrappedMethods:
    def it_is_stable_when_a_classmethod_only_helper_is_unchanged(self, tmp_path: Path) -> None:
        helper = tmp_path / 'gremlin_ops.py'
        operator = _path_load_operator(helper, CLASSMETHOD_HELPER.format(delta=1))

        assert installed_versions_fingerprint([operator], tmp_path) == installed_versions_fingerprint(
            [operator], tmp_path
        )
