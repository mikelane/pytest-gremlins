"""An operator helper loaded by file path always misses the cache (#882).

A conftest that loads its helper with ``spec_from_file_location`` never registers it in ``sys.modules``, and no
inference from the class's methods can prove which file defined it: decorators, generated dataclass methods and
methods copied from a same-named class all carry code from other files. The pessimistic answer is a fresh token on
every call, so a verdict is recomputed and never reused stale. A helper that is importable still hashes its file.
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
LOCAL_BASE_MODULE = (
    'class HelperOperator:\n'
    '    name = "helper"\n'
    '    description = "x"\n'
    '\n'
    '    def can_mutate(self, node):\n'
    '        return True\n'
)
PLAIN_HELPER = 'class HelperOperator:\n    name = "helper"\n    description = "x"\n'
DECORATED_HELPER = (
    'from support_decorators import passthrough\n'
    '\n'
    '\n'
    'class HelperOperator:\n'
    '    name = "helper"\n'
    '    description = "x"\n'
    '\n'
    '    @passthrough\n'
    '    def can_mutate(self, node):\n'
    '        return True\n'
)
DATACLASS_HELPER = (
    'import dataclasses\n'
    '\n'
    'from pytest_gremlins.operators.comparison import ComparisonOperator\n'
    '\n'
    '\n'
    '@dataclasses.dataclass\n'
    'class HelperOperator(ComparisonOperator):\n'
    '    delta: int = 1\n'
)
CLASSMETHOD_HELPER = (
    'class HelperOperator:\n'
    '    name = "helper"\n'
    '    description = "x"\n'
    '\n'
    '    @classmethod\n'
    '    def can_mutate(cls, node):\n'
    '        return True\n'
)
BUILTIN_NAME_COPY_HELPER = (
    'from pytest_gremlins.operators.comparison import ComparisonOperator as _Base\n'
    '\n'
    '\n'
    'class ComparisonOperator(_Base):\n'
    '    can_mutate = _Base.can_mutate\n'
    '\n'
    '\n'
    'HelperOperator = ComparisonOperator\n'
)
LOCAL_NAME_COPY_HELPER = (
    'from support_base import HelperOperator as _Base\n'
    '\n'
    '\n'
    'class HelperOperator(_Base):\n'
    '    can_mutate = _Base.can_mutate\n'
)
UNRELATED_MODULE = 'VALUE = 1\n'


def _path_load_operator(path: Path, source: str, module_name: str = 'path_loaded_helper') -> object:
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HelperOperator()


@pytest.fixture
def support_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    support = tmp_path / 'support'
    support.mkdir()
    (support / 'support_decorators.py').write_text(DECORATOR_MODULE)
    (support / 'support_base.py').write_text(LOCAL_BASE_MODULE)
    monkeypatch.syspath_prepend(str(support))
    monkeypatch.delitem(sys.modules, 'support_decorators', raising=False)
    monkeypatch.delitem(sys.modules, 'support_base', raising=False)


@pytest.mark.medium
@pytest.mark.usefixtures('support_modules')
class DescribePathLoadedOperatorHelper:
    @pytest.mark.parametrize(
        'source',
        [
            pytest.param(PLAIN_HELPER, id='plain-class'),
            pytest.param(DECORATED_HELPER, id='decorated-method'),
            pytest.param(DATACLASS_HELPER, id='fields-only-dataclass'),
            pytest.param(CLASSMETHOD_HELPER, id='classmethod-only'),
            pytest.param(BUILTIN_NAME_COPY_HELPER, id='method-copied-from-same-named-builtin'),
            pytest.param(LOCAL_NAME_COPY_HELPER, id='method-copied-from-same-named-local-class'),
        ],
    )
    def it_gets_a_fresh_token_on_every_call(self, tmp_path: Path, source: str) -> None:
        root = tmp_path / 'project'
        root.mkdir()
        operator = _path_load_operator(root / 'gremlin_ops.py', source)

        first = installed_versions_fingerprint([operator], root)
        second = installed_versions_fingerprint([operator], root)

        assert first != second

    def it_never_hashes_an_unrelated_module_that_shares_the_spec_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'unrelated.py').write_text(UNRELATED_MODULE)
        monkeypatch.syspath_prepend(str(root))
        monkeypatch.delitem(sys.modules, 'unrelated', raising=False)
        importlib.import_module('unrelated')
        monkeypatch.setitem(sys.modules, 'unrelated', sys.modules['unrelated'])
        operator = _path_load_operator(root / 'gremlin_ops.py', PLAIN_HELPER, module_name='unrelated')

        first = installed_versions_fingerprint([operator], root)
        second = installed_versions_fingerprint([operator], root)

        assert first != second
        assert 'unrelated.py' not in first

    def it_gets_a_fresh_token_for_a_class_defined_inside_a_function(self, tmp_path: Path) -> None:
        root = tmp_path / 'project'
        root.mkdir()
        source = (
            'def build():\n'
            '    class HelperOperator:\n'
            '        name = "helper"\n'
            '        description = "x"\n'
            '    return HelperOperator\n'
            '\n'
            '\n'
            'HelperOperator = build()\n'
        )
        operator = _path_load_operator(root / 'gremlin_ops.py', source)

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)
