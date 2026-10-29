"""A project-local operator helper makes every run miss the cache, wherever its class is defined (#882).

The key never trusts a helper file: a package that re-exports a class, a fallback or ``TYPE_CHECKING`` decoy, a
class nested in a block or another class, and an unreadable or unparseable file all get the always-miss token.
Restoring cache hits for helpers is tracked in #887.
"""

from __future__ import annotations

import importlib
import sys
from typing import (
    TYPE_CHECKING,
    NamedTuple,
)

import pytest

from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

CLASS_V1 = 'class HelperOperator:\n    name = "helper"\n    description = "v1"\n'
CLASS_V2 = CLASS_V1.replace('"v1"', '"v2 edited"')
REEXPORT_INIT = 'from gremlin_pkg._impl import HelperOperator\n\nHelperOperator.__module__ = "gremlin_pkg"\n'
FALLBACK_DECOY_INIT = (
    'try:\n'
    '    from gremlin_pkg._impl import HelperOperator\n'
    'except ImportError:\n'
    '    class HelperOperator:\n'
    '        name = "fallback"\n'
    'HelperOperator.__module__ = "gremlin_pkg"\n'
)
TYPE_CHECKING_DECOY_INIT = (
    'from typing import TYPE_CHECKING\n'
    'if TYPE_CHECKING:\n'
    '    class HelperOperator:\n'
    '        name: str\n'
    'else:\n'
    '    from gremlin_pkg._impl import HelperOperator\n'
    '    HelperOperator.__module__ = "gremlin_pkg"\n'
)
NESTED_V1 = 'class Outer:\n    class HelperOperator:\n        name = "helper"\n        description = "v1"\n'
NESTED_V2 = NESTED_V1.replace('"v1"', '"v2 edited"')
IF_BLOCK_V1 = 'if True:\n    class HelperOperator:\n        name = "helper"\n        description = "v1"\n'
IF_BLOCK_V2 = IF_BLOCK_V1.replace('"v1"', '"v2 edited"')
TRY_BLOCK_V1 = (
    'try:\n'
    '    class HelperOperator:\n'
    '        name = "helper"\n'
    '        description = "v1"\n'
    'except ImportError:\n'
    '    pass\n'
)
TRY_BLOCK_V2 = TRY_BLOCK_V1.replace('"v1"', '"v2 edited"')
TWO_BRANCH_V1 = (
    'import sys\n'
    'if sys.version_info >= (3, 0):\n'
    '    class HelperOperator:\n'
    '        name = "helper"\n'
    '        description = "v1"\n'
    'else:\n'
    '    class HelperOperator:\n'
    '        name = "old"\n'
)
TWO_BRANCH_V2 = TWO_BRANCH_V1.replace('"v1"', '"v2 edited"')
BOM_PREFIX = '﻿# -*- coding: utf-8 -*-\n'
UNPARSEABLE = 'def broken(:\n'
DEEP_EXPRESSION_LINE = 'X = ' + ' + '.join(['1'] * 20000) + '\n'


class HelperCase(NamedTuple):
    init_v1: str
    init_v2: str
    impl_v1: str | None
    impl_v2: str | None
    qualname: str


HELPER_CASES = [
    pytest.param(
        HelperCase(REEXPORT_INIT, REEXPORT_INIT, CLASS_V1, CLASS_V2, 'HelperOperator'), id='reexported-from-impl'
    ),
    pytest.param(
        HelperCase(FALLBACK_DECOY_INIT, FALLBACK_DECOY_INIT, CLASS_V1, CLASS_V2, 'HelperOperator'), id='fallback-decoy'
    ),
    pytest.param(
        HelperCase(
            TYPE_CHECKING_DECOY_INIT,
            TYPE_CHECKING_DECOY_INIT,
            CLASS_V1,
            CLASS_V2,
            'HelperOperator',
        ),
        id='type-checking-decoy',
    ),
    pytest.param(HelperCase(CLASS_V1, CLASS_V2, None, None, 'HelperOperator'), id='defined-in-init'),
    pytest.param(HelperCase(NESTED_V1, NESTED_V2, None, None, 'Outer.HelperOperator'), id='nested-in-class'),
    pytest.param(HelperCase(IF_BLOCK_V1, IF_BLOCK_V2, None, None, 'HelperOperator'), id='inside-if-block'),
    pytest.param(HelperCase(TRY_BLOCK_V1, TRY_BLOCK_V2, None, None, 'HelperOperator'), id='inside-try-block'),
    pytest.param(HelperCase(TWO_BRANCH_V1, TWO_BRANCH_V2, None, None, 'HelperOperator'), id='two-branch-definitions'),
    pytest.param(
        HelperCase(BOM_PREFIX + CLASS_V1, BOM_PREFIX + CLASS_V2, None, None, 'HelperOperator'),
        id='bom-and-coding-cookie',
    ),
]


def _import_helper(monkeypatch: pytest.MonkeyPatch, qualname: str = 'HelperOperator') -> object:
    monkeypatch.delitem(sys.modules, 'gremlin_pkg', raising=False)
    monkeypatch.delitem(sys.modules, 'gremlin_pkg._impl', raising=False)
    importlib.invalidate_caches()
    holder: object = importlib.import_module('gremlin_pkg')
    for part in qualname.split('.'):
        holder = getattr(holder, part)
    return holder()  # type: ignore[operator]


def _make_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, init_source: str, impl_source: str | None = None
) -> tuple[Path, Path]:
    root = tmp_path / 'project'
    package = root / 'gremlin_pkg'
    package.mkdir(parents=True)
    (package / '__init__.py').write_bytes(init_source.encode())
    if impl_source is not None:
        (package / '_impl.py').write_text(impl_source)
    monkeypatch.syspath_prepend(str(root))
    return root, package


@pytest.mark.medium
class DescribeProjectLocalOperatorHelperKey:
    @pytest.mark.parametrize('case', HELPER_CASES)
    def it_changes_the_key_when_the_helper_is_edited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: HelperCase
    ) -> None:
        root, package = _make_package(tmp_path, monkeypatch, case.init_v1, case.impl_v1)
        before = installed_versions_fingerprint([_import_helper(monkeypatch, case.qualname)], root)
        (package / '__init__.py').write_bytes(case.init_v2.encode())
        if case.impl_v2 is not None:
            (package / '_impl.py').write_text(case.impl_v2)

        after = installed_versions_fingerprint([_import_helper(monkeypatch, case.qualname)], root)

        assert before != after

    @pytest.mark.parametrize('case', HELPER_CASES)
    def it_changes_the_key_on_every_call_for_an_unchanged_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: HelperCase
    ) -> None:
        root, _ = _make_package(tmp_path, monkeypatch, case.init_v1, case.impl_v1)
        operator = _import_helper(monkeypatch, case.qualname)

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)

    def it_misses_when_the_file_no_longer_parses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, CLASS_V1)
        operator = _import_helper(monkeypatch)
        (package / '__init__.py').write_text(UNPARSEABLE)

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)

    def it_misses_when_the_file_is_unreadable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root, package = _make_package(tmp_path, monkeypatch, CLASS_V1)
        operator = _import_helper(monkeypatch)
        (package / '__init__.py').unlink()

        assert installed_versions_fingerprint([operator], root) != installed_versions_fingerprint([operator], root)

    def it_returns_a_fingerprint_for_a_defining_file_with_a_deep_expression(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, package = _make_package(tmp_path, monkeypatch, CLASS_V1)
        operator = _import_helper(monkeypatch)
        (package / '__init__.py').write_text(DEEP_EXPRESSION_LINE + CLASS_V1)

        assert 'local-operator=' in installed_versions_fingerprint([operator], root)
