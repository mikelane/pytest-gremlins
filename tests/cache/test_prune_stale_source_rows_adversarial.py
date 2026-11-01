"""Adversarial probes for the #930 prune (run 2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation.transformer import gremlin_file_prefix
from pytest_gremlins.plugin import _prune_stale_cache_rows

if TYPE_CHECKING:
    from pathlib import Path

FILE_A = 'pkg66/models.py'
FILE_C = 'other/service.py'
TAIL = 'tests:opt=0:reruns=0x0.0:rr={}:v=ver:rf20'


@pytest.mark.medium
class DescribeAdversarialPrune:
    def it_keeps_current_rows_of_a_non_colliding_file_left_out_of_this_run(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        row_c = f'{gremlin_file_prefix(FILE_C)}_g000:HASH_C:{TAIL}'
        cache._store.put(row_c, {'status': 'zapped'})  # type: ignore[typeddict-item]
        session = SimpleNamespace(cache=cache, source_hashes={FILE_A: 'HASH_A'})

        _prune_stale_cache_rows(session)  # type: ignore[arg-type]

        assert row_c in sorted(cache._store.keys())
        cache.close()

    def it_treats_regex_metacharacters_in_hashes_and_stems_literally(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        prefix = 'a.b+c_ab12'
        current = f'{prefix}_g1:h.*:{TAIL}'
        stale = f'{prefix}_g1:hXY:{TAIL}'
        lookalike = f'aXb+c_ab12_g1:old:{TAIL}'
        for key in (current, stale, lookalike):
            cache._store.put(key, {'status': 'zapped'})  # type: ignore[typeddict-item]

        cache.prune_stale_sources({prefix: {'h.*'}})

        assert sorted(cache._store.keys()) == sorted([current, lookalike])
        cache.close()

    def it_keeps_three_colliding_files_current_rows_and_drops_their_stale_ones(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        prefix = 'models_ac78'
        keep = [f'{prefix}_g{n}:H{n}:{TAIL}' for n in (1, 2, 1000)]
        drop = [f'{prefix}_g{n}:OLD:{TAIL}' for n in (1, 2, 1000)]
        for key in keep + drop:
            cache._store.put(key, {'status': 'zapped'})  # type: ignore[typeddict-item]

        cache.prune_stale_sources({prefix: {'H1', 'H2', 'H1000'}})

        assert sorted(cache._store.keys()) == sorted(keep)
        cache.close()

    def it_does_not_treat_a_current_hash_prefix_as_current(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        prefix = 'mod_ab12'
        stale = f'{prefix}_g1:abcdef:{TAIL}'
        cache._store.put(stale, {'status': 'zapped'})  # type: ignore[typeddict-item]

        cache.prune_stale_sources({prefix: {'abc', 'abcdefg'}})

        assert cache._store.keys() == []
        cache.close()
