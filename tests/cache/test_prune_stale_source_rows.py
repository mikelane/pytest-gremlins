"""Rows stranded by an edited source file are pruned at run start (#930)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.store import ResultStore

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult

KEY_TAIL = 'tests:opt=0:reruns=0x0.0:rr={}:v=ver:rf20'
RESULT: CachedGremlinResult = {'status': 'zapped'}  # type: ignore[typeddict-item]


def _key(gremlin_id: str, source_hash: str, tail: str = KEY_TAIL) -> str:
    return f'{gremlin_id}:{source_hash}:{tail}'


@pytest.fixture
def store(tmp_path: Path):
    with ResultStore(tmp_path / 'results.db') as opened:
        yield opened


@pytest.mark.medium
class DescribePruneStaleSourceHashes:
    def it_drops_rows_of_an_edited_file_and_keeps_other_files(self, store: ResultStore) -> None:
        store.put(_key('mod_ab12_g001', 'H1'), RESULT)
        store.put(_key('mod_ab12_g002', 'H1'), RESULT)
        store.put(_key('other_cd34_g001', 'H1'), RESULT)

        store.prune_stale_source_hashes({'mod_ab12': 'H2'})

        assert store.keys() == [_key('other_cd34_g001', 'H1')]
        assert store.count() == 1

    def it_misses_the_dropped_ids_under_the_old_hash(self, store: ResultStore) -> None:
        store.put(_key('mod_ab12_g001', 'H1'), RESULT)

        store.prune_stale_source_hashes({'mod_ab12': 'H2'})

        assert store.get(_key('mod_ab12_g001', 'H1')) is None

    def it_keeps_rows_with_the_current_hash_under_any_other_key_part(self, store: ResultStore) -> None:
        kept = [
            _key('mod_ab12_g001', 'H2'),
            _key('mod_ab12_g001', 'H2', 'other-tests:opt=2:reruns=1x0.0:rr={}:v=ver:pytester:xdist:rf20'),
        ]
        for key in kept:
            store.put(key, RESULT)

        store.prune_stale_source_hashes({'mod_ab12': 'H2'})

        assert sorted(store.keys()) == sorted(kept)

    def it_does_not_catch_a_longer_stem_sharing_the_prefix(self, store: ResultStore) -> None:
        longer = _key('mod_ab12_gx_ef56_g001', 'H1')
        lookalike = _key('mod_ab12_gx', 'H1')
        store.put(longer, RESULT)
        store.put(lookalike, RESULT)

        store.prune_stale_source_hashes({'mod_ab12': 'H2'})

        assert sorted(store.keys()) == sorted([longer, lookalike])

    def it_leaves_files_not_named_in_the_call_untouched(self, store: ResultStore) -> None:
        store.put(_key('gone_ef56_g001', 'H1'), RESULT)

        store.prune_stale_source_hashes({'mod_ab12': 'H2'})

        assert store.count() == 1

    def it_prunes_several_files_in_one_call(self, store: ResultStore) -> None:
        store.put(_key('a_0001_g001', 'OLD'), RESULT)
        store.put(_key('b_0002_g001', 'OLD'), RESULT)
        store.put(_key('b_0002_g002', 'NEW'), RESULT)

        store.prune_stale_source_hashes({'a_0001': 'NEW', 'b_0002': 'NEW'})

        assert store.keys() == [_key('b_0002_g002', 'NEW')]

    def it_keeps_rows_whose_prefix_has_regex_or_like_metacharacters(self, store: ResultStore) -> None:
        store.put(_key('a.b%_1234_g001', 'OLD'), RESULT)
        store.put(_key('axb%_1234_g001', 'OLD'), RESULT)

        store.prune_stale_source_hashes({'a.b%_1234': 'NEW'})

        assert store.keys() == [_key('axb%_1234_g001', 'OLD')]
