"""Cache keys must change when a conftest.py above a covering test changes (#702)."""

from pathlib import Path
import threading

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.hasher import ContentHasher


def _session_for(rootdir: Path, node_ids: list[str]) -> plugin.GremlinSession:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    session.test_node_ids = {node_id: node_id for node_id in node_ids}
    session.test_name_to_node_ids = {node_id.split('::')[-1]: [node_id] for node_id in node_ids}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir)
    return session


def _write_project(root: Path) -> None:
    (root / 'tests' / 'sub').mkdir(parents=True)
    (root / 'tests' / 'sub' / 'test_a.py').write_text('def test_a(): pass\n')
    (root / 'tests' / 'sub' / 'test_b.py').write_text('def test_b(): pass\n')
    (root / 'conftest.py').write_text('X = 1\n')
    (root / 'tests' / 'conftest.py').write_text('Y = 1\n')


@pytest.mark.medium
class DescribeConftestFoldedIntoTestHash:
    @pytest.mark.parametrize('conftest', ['conftest.py', 'tests/conftest.py'])
    def it_changes_the_test_hash_when_a_conftest_on_the_path_changes(self, tmp_path: Path, conftest: str) -> None:
        _write_project(tmp_path)
        node_id = 'tests/sub/test_a.py::test_a'
        before = _session_for(tmp_path, [node_id]).test_hashes['tests/sub/test_a.py']

        (tmp_path / conftest).write_text('CHANGED = 2\n')

        after = _session_for(tmp_path, [node_id]).test_hashes['tests/sub/test_a.py']
        assert before != after

    def it_ignores_a_conftest_in_an_unrelated_directory(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        (tmp_path / 'other').mkdir()
        (tmp_path / 'other' / 'conftest.py').write_text('Z = 1\n')
        node_id = 'tests/sub/test_a.py::test_a'
        before = _session_for(tmp_path, [node_id]).test_hashes['tests/sub/test_a.py']

        (tmp_path / 'other' / 'conftest.py').write_text('Z = 2\n')

        assert _session_for(tmp_path, [node_id]).test_hashes['tests/sub/test_a.py'] == before

    def it_keeps_the_bare_file_hash_when_no_conftest_is_on_the_path(self, tmp_path: Path) -> None:
        (tmp_path / 'tests').mkdir()
        test_file = tmp_path / 'tests' / 'test_a.py'
        test_file.write_text('def test_a(): pass\n')

        session = _session_for(tmp_path, ['tests/test_a.py::test_a'])

        assert session.test_hashes['tests/test_a.py'] == ContentHasher().hash_file(test_file)


@pytest.mark.medium
class DescribeUnmatchedSelectedTestIsNotCached:
    def it_treats_a_selected_test_without_a_node_id_as_unhashed(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        session = _session_for(tmp_path, ['tests/sub/test_a.py::test_a'])

        assert plugin._selection_has_unhashed_test_file(['test_ghost'], session) is True

    def it_accepts_a_selected_test_with_a_hashed_file(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        session = _session_for(tmp_path, ['tests/sub/test_a.py::test_a'])

        assert plugin._selection_has_unhashed_test_file(['test_a'], session) is False


@pytest.mark.medium
class DescribeFilesystemRootAsRootdir:
    def it_finishes_hashing_when_rootdir_is_the_filesystem_root(self, tmp_path: Path) -> None:
        test_file = tmp_path / 'test_a.py'
        test_file.write_text('def test_a(): pass\n')
        filesystem_root = Path(tmp_path.anchor)
        relative = test_file.relative_to(filesystem_root).as_posix()
        hashes: list[str] = []
        worker = threading.Thread(
            target=lambda: hashes.append(
                plugin._hash_test_file_with_conftests(ContentHasher(), filesystem_root, relative)
            ),
            daemon=True,
        )

        worker.start()
        worker.join(timeout=5)

        assert hashes == [ContentHasher().hash_file(test_file)]
