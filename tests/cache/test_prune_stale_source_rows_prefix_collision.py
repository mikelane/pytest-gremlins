"""Two target files whose gremlin-id prefixes collide must not prune each other's rows (#930)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation.transformer import gremlin_file_prefix
from pytest_gremlins.plugin import _prune_stale_cache_rows

if TYPE_CHECKING:
    from pathlib import Path

# Same stem, different directories, same 4-hex path hash (md5 prefix is only 16 bits).
FILE_A = 'pkg66/models.py'
FILE_B = 'pkg456/models.py'
TAIL = 'tests:opt=0:reruns=0x0.0:rr={}:v=ver:rf20'


@pytest.mark.medium
class DescribePruneWithCollidingPrefixes:
    def it_keeps_current_hash_rows_of_both_files_when_their_prefixes_collide(self, tmp_path: Path) -> None:
        assert gremlin_file_prefix(FILE_A) == gremlin_file_prefix(FILE_B)
        prefix = gremlin_file_prefix(FILE_A)
        cache = IncrementalCache(tmp_path / 'cache')
        row_a = f'{prefix}_g000:HASH_A:{TAIL}'
        row_b = f'{prefix}_g000:HASH_B:{TAIL}'
        cache._store.put(row_a, {'status': 'zapped'})  # type: ignore[typeddict-item]
        cache._store.put(row_b, {'status': 'zapped'})  # type: ignore[typeddict-item]
        session = SimpleNamespace(cache=cache, source_hashes={FILE_A: 'HASH_A', FILE_B: 'HASH_B'})

        _prune_stale_cache_rows(session)  # type: ignore[arg-type]

        assert sorted(cache._store.keys()) == sorted([row_a, row_b])
        cache.close()
