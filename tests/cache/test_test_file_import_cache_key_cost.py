"""Hashing many test files reads, parses and stats each file a bounded number of times (#910).

The counts do not depend on machine load, unlike a wall-clock budget.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path
from typing import cast

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.hasher import ContentHasher

FILE_COUNT = 200
IMPORTS = (
    'import os\nimport sys\nimport json\nimport re\nimport pathlib\nimport typing\nimport collections\n'
    'import pytest\nfrom unittest.mock import MagicMock, patch, call\nfrom tests.helpers import make\n'
)
STAT_CALLS_PER_FILE = 4


def _hash_session(rootdir: Path, node_ids: list[str]) -> None:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    session.test_node_ids = {node_id: node_id for node_id in node_ids}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir)


@pytest.mark.medium
class DescribeTestFileHashingCost:
    def it_stats_a_bounded_number_of_paths_per_test_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        deep = tmp_path / 'tests' / 'a' / 'b' / 'c'
        deep.mkdir(parents=True)
        (tmp_path / 'tests' / '__init__.py').write_text('')
        (tmp_path / 'tests' / 'helpers.py').write_text('def make(): pass\n')
        for index in range(FILE_COUNT):
            (deep / f'test_m{index}.py').write_text(IMPORTS + f'def test_{index}(): pass\n')
        node_ids = [f'tests/a/b/c/test_m{index}.py::test_{index}' for index in range(FILE_COUNT)]
        stat_calls = 0
        real_is_file = Path.is_file

        def counting_is_file(self: Path) -> bool:
            nonlocal stat_calls
            stat_calls += 1
            return real_is_file(self)

        monkeypatch.setattr(Path, 'is_file', counting_is_file)

        _hash_session(tmp_path, node_ids)

        assert stat_calls < STAT_CALLS_PER_FILE * FILE_COUNT

    def it_parses_and_hashes_each_file_of_an_import_chain_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tests = tmp_path / 'tests'
        tests.mkdir()
        for index in range(FILE_COUNT):
            following = f'from tests.test_m{index + 1} import X\n' if index + 1 < FILE_COUNT else ''
            (tests / f'test_m{index}.py').write_text(f'{following}X = {index}\n')
        node_ids = [f'tests/test_m{index}.py::test_x' for index in range(FILE_COUNT)]
        parses: collections.Counter[bytes] = collections.Counter()
        hashes: collections.Counter[Path] = collections.Counter()
        real_parse = ast.parse
        real_hash_file = ContentHasher.hash_file

        def counting_parse(source: bytes, *args: object, **kwargs: object) -> ast.Module:
            parses[source] += 1
            return cast('ast.Module', real_parse(source, *args, **kwargs))

        def counting_hash_file(self: ContentHasher, path: Path) -> str:
            hashes[path] += 1
            return real_hash_file(self, path)

        monkeypatch.setattr(ast, 'parse', counting_parse)
        monkeypatch.setattr(ContentHasher, 'hash_file', counting_hash_file)

        _hash_session(tmp_path, node_ids)

        assert (max(parses.values()), max(hashes.values())) == (1, 1)
