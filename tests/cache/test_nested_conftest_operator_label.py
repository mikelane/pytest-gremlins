"""A conftest operator below the rootdir is named by relative path and content hash in the fingerprint (#899)."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.versions import (
    CACHE_VERSION,
    installed_versions_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.operators.protocol import GremlinOperator

BASE = f'cache-version={CACHE_VERSION}'
MODULE_NAME = 'nested_conftest_fake_module'


def _operator_from(monkeypatch: pytest.MonkeyPatch, conftest: Path) -> GremlinOperator:
    """Build an operator whose class claims to be defined in ``conftest``."""
    module = types.ModuleType(MODULE_NAME)
    module.__file__ = str(conftest)
    monkeypatch.setitem(sys.modules, MODULE_NAME, module)
    operator_class = type('FakeOperator', (), {'__module__': MODULE_NAME, 'name': 'fake', 'description': 'x'})
    operator: GremlinOperator = operator_class()
    return operator


@pytest.fixture
def nested_conftest(tmp_path: Path) -> Path:
    path = tmp_path / 'a' / 'conftest.py'
    path.parent.mkdir()
    path.write_text('X = 1\n')
    return path


@pytest.mark.medium
class DescribeNestedConftestOperatorLabel:
    def it_names_a_below_rootdir_conftest_by_relative_path(
        self, tmp_path: Path, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)

        fingerprint = installed_versions_fingerprint([operator], tmp_path)

        assert fingerprint.startswith(f'{BASE}|nested-conftest-operator=a/conftest.py:')

    def it_is_stable_when_the_conftest_is_unchanged(
        self, tmp_path: Path, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)

        first = installed_versions_fingerprint([operator], tmp_path)
        second = installed_versions_fingerprint([operator], tmp_path)

        assert first == second

    def it_changes_when_the_conftest_content_changes(
        self, tmp_path: Path, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)
        before = installed_versions_fingerprint([operator], tmp_path)

        nested_conftest.write_text('X = 2\n')
        after = installed_versions_fingerprint([operator], tmp_path)

        assert before != after

    def it_adds_nothing_for_the_rootdir_conftest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root_conftest = tmp_path / 'conftest.py'
        root_conftest.write_text('X = 1\n')
        operator = _operator_from(monkeypatch, root_conftest)

        fingerprint = installed_versions_fingerprint([operator], tmp_path)

        assert fingerprint == BASE

    def it_names_the_conftest_by_file_name_when_no_rootdir_is_known(
        self, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)

        fingerprint = installed_versions_fingerprint([operator], None)

        assert fingerprint.startswith(f'{BASE}|nested-conftest-operator=conftest.py:')

    def it_always_misses_when_the_conftest_cannot_be_read(
        self, tmp_path: Path, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)
        nested_conftest.unlink()

        first = installed_versions_fingerprint([operator], tmp_path)
        second = installed_versions_fingerprint([operator], tmp_path)

        assert f'|local-operator={MODULE_NAME}:unreadable-' in first
        assert first != second

    def it_always_misses_for_a_conftest_above_the_rootdir(
        self, tmp_path: Path, nested_conftest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator = _operator_from(monkeypatch, nested_conftest)
        rootdir = tmp_path / 'a' / 'project'
        rootdir.mkdir()

        fingerprint = installed_versions_fingerprint([operator], rootdir)

        assert f'|local-operator={MODULE_NAME}:unreadable-' in fingerprint
        assert 'nested-conftest-operator=' not in fingerprint
