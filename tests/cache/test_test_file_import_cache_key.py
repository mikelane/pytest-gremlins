"""A test file's cache key follows the other test files it imports, statically (#910)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.hasher import ContentHasher

TEST_FILE = 'tests/test_a.py'


def _test_hash(
    rootdir: Path, test_file: str = TEST_FILE, python_files: tuple[str, ...] = plugin.DEFAULT_TEST_FILE_PATTERNS
) -> str:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    session.test_node_ids = {f'{test_file}::test_x': f'{test_file}::test_x'}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir, python_files)
    return session.test_hashes[test_file]


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _assert_edit_changes_key(root: Path, edited: str) -> None:
    before = _test_hash(root)
    (root / edited).write_text('CHANGED = 2\n')
    assert _test_hash(root) != before


@pytest.mark.medium
class DescribeImportedTestFilesFoldedIntoTestHash:
    def it_misses_the_cache_after_editing_a_test_file_imported_with_from_import(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {'tests/test_a.py': 'from tests.test_b import make\n', 'tests/test_b.py': 'def make(): return 1\n'},
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_misses_the_cache_after_editing_a_test_file_imported_with_plain_import(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'import tests.test_b\n', 'tests/test_b.py': 'X = 1\n'})

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_misses_the_cache_after_editing_a_test_file_imported_by_sibling_name(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'import test_b\n', 'tests/test_b.py': 'X = 1\n'})

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_misses_the_cache_after_editing_a_test_file_imported_relatively(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': '',
                'tests/test_a.py': 'from .test_b import make\n',
                'tests/test_b.py': 'def make(): return 1\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_misses_the_cache_after_editing_a_test_file_imported_from_a_parent_package(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': '',
                'tests/unit/__init__.py': '',
                'tests/unit/test_a.py': 'from .. import test_b\n',
                'tests/test_b.py': 'X = 1\n',
            },
        )
        before = _test_hash(tmp_path, 'tests/unit/test_a.py')

        (tmp_path / 'tests' / 'test_b.py').write_text('X = 2\n')

        assert _test_hash(tmp_path, 'tests/unit/test_a.py') != before

    def it_misses_the_cache_after_editing_a_test_module_imported_as_from_package_import_module(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': '',
                'tests/test_a.py': 'from tests import test_b\n',
                'tests/test_b.py': 'X = 1\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_misses_the_cache_after_editing_a_test_file_imported_by_a_conftest(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/conftest.py': 'from tests.test_b import make\n',
                'tests/test_a.py': 'def test_a(): pass\n',
                'tests/test_b.py': 'def make(): return 1\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_b.py')

    def it_follows_imports_transitively(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/test_a.py': 'from tests.test_b import make\n',
                'tests/test_b.py': 'from tests.test_c import make\n',
                'tests/test_c.py': 'def make(): return 1\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_c.py')

    def it_follows_a_test_file_imported_through_a_helper_module(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/test_a.py': 'from tests.helpers import make\n',
                'tests/helpers.py': 'from tests.test_c import make\n',
                'tests/test_c.py': 'def make(): return 1\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_c.py')

    def it_terminates_on_an_import_cycle_and_still_tracks_its_members(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/test_a.py': 'from tests.test_b import X\n',
                'tests/test_b.py': 'from tests.test_c import X\n',
                'tests/test_c.py': 'from tests.test_b import X\nfrom tests.test_a import X\n',
            },
        )

        _assert_edit_changes_key(tmp_path, 'tests/test_c.py')

    def it_does_not_crash_on_an_imported_test_file_with_a_syntax_error(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'from tests.test_b import X\n', 'tests/test_b.py': 'def broken(:\n'})
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / 'test_b.py').write_text('def still_broken(:\n')

        assert _test_hash(tmp_path) != before

    def it_does_not_crash_when_the_test_file_itself_has_a_syntax_error(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'def broken(:\n'})

        assert _test_hash(tmp_path) == ContentHasher().hash_file(tmp_path / TEST_FILE)

    def it_keeps_the_key_when_an_unimported_test_file_changes(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'X = 1\n', 'tests/test_b.py': 'Y = 1\n'})
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / 'test_b.py').write_text('Y = 2\n')

        assert _test_hash(tmp_path) == before

    def it_ignores_imports_that_resolve_outside_the_test_root(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/test_a.py': 'import test_outside\n', 'other/test_outside.py': 'X = 1\n'})
        before = _test_hash(tmp_path)

        (tmp_path / 'other' / 'test_outside.py').write_text('X = 2\n')

        assert _test_hash(tmp_path) == before

    def it_does_not_follow_a_dynamic_import(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/test_a.py': 'import importlib\nimportlib.import_module("tests." + "test_b")\n',
                'tests/test_b.py': 'X = 1\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / 'test_b.py').write_text('X = 2\n')

        assert _test_hash(tmp_path) == before


@pytest.mark.medium
class DescribeTestFilePatternsFromPythonFiles:
    def it_treats_a_file_matching_a_custom_python_files_pattern_as_a_test_file(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/check_a.py': 'X = 1\n', 'tests/check_b.py': 'Y = 1\n'})
        before = _test_hash(tmp_path, 'tests/check_a.py', ('check_*.py',))

        (tmp_path / 'tests' / 'check_b.py').write_text('Y = 2\n')

        assert _test_hash(tmp_path, 'tests/check_a.py', ('check_*.py',)) == before

    def it_treats_a_default_test_name_as_a_helper_under_a_custom_pattern(self, tmp_path: Path) -> None:
        _write(tmp_path, {'tests/check_a.py': 'X = 1\n', 'tests/test_utils.py': 'Y = 1\n'})
        before = _test_hash(tmp_path, 'tests/check_a.py', ('check_*.py',))

        (tmp_path / 'tests' / 'test_utils.py').write_text('Y = 2\n')

        assert _test_hash(tmp_path, 'tests/check_a.py', ('check_*.py',)) != before
