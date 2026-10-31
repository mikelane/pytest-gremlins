"""Cache keys must change when a non-test module under the test roots changes (#760)."""

from pathlib import Path

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.hasher import ContentHasher

NODE_ID = 'tests/test_a.py::test_a'
TEST_FILE = 'tests/test_a.py'


def _test_hash(rootdir: Path) -> str:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    session.test_node_ids = {NODE_ID: NODE_ID}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir)
    return session.test_hashes[TEST_FILE]


def _write_project(root: Path) -> None:
    (root / 'tests' / 'support').mkdir(parents=True)
    (root / 'tests' / 'test_a.py').write_text('def test_a(): pass\n')
    (root / 'tests' / 'support' / 'fixtures.py').write_text('X = 1\n')
    (root / 'tests' / 'helpers.py').write_text('Y = 1\n')
    (root / 'other').mkdir()
    (root / 'other' / 'unrelated.py').write_text('Z = 1\n')


@pytest.mark.medium
class DescribeHelperModulesFoldedIntoTestHash:
    @pytest.mark.parametrize('helper', ['tests/support/fixtures.py', 'tests/helpers.py'])
    def it_misses_the_cache_after_a_fixture_helper_module_edit(self, tmp_path: Path, helper: str) -> None:
        _write_project(tmp_path)
        before = _test_hash(tmp_path)

        (tmp_path / helper).write_text('CHANGED = 2\n')

        assert _test_hash(tmp_path) != before

    def it_misses_the_cache_after_a_new_helper_module_appears(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / 'support' / 'extra.py').write_text('W = 1\n')

        assert _test_hash(tmp_path) != before

    def it_keeps_the_hash_when_a_module_outside_the_test_roots_changes(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        before = _test_hash(tmp_path)

        (tmp_path / 'other' / 'unrelated.py').write_text('Z = 2\n')

        assert _test_hash(tmp_path) == before

    def it_keeps_the_hash_when_a_pycache_file_changes(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        (tmp_path / 'tests' / '__pycache__').mkdir()
        (tmp_path / 'tests' / '__pycache__' / 'junk.py').write_text('A = 1\n')
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / '__pycache__' / 'junk.py').write_text('A = 2\n')

        assert _test_hash(tmp_path) == before

    def it_keeps_the_hash_when_a_sibling_test_file_changes(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        (tmp_path / 'tests' / 'test_b.py').write_text('def test_b(): pass\n')
        before = _test_hash(tmp_path)

        (tmp_path / 'tests' / 'test_b.py').write_text('def test_b(): assert True\n')

        assert _test_hash(tmp_path) == before

    def it_hashes_identically_on_repeated_runs(self, tmp_path: Path) -> None:
        _write_project(tmp_path)

        assert _test_hash(tmp_path) == _test_hash(tmp_path)

    def it_keeps_the_bare_file_hash_when_no_helper_exists(self, tmp_path: Path) -> None:
        (tmp_path / 'tests').mkdir()
        test_file = tmp_path / 'tests' / 'test_a.py'
        test_file.write_text('def test_a(): pass\n')

        assert _test_hash(tmp_path) == ContentHasher().hash_file(test_file)
