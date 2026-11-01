"""The prune matcher agrees with the key shape the real gremlin-id and key producers emit (#930)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation.transformer import (
    collect_gremlins,
    gremlin_file_prefix,
)

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = 'def f(a, b):\n    return a < b\n'
RESULT = {'status': 'zapped'}


@pytest.mark.medium
class DescribePruneAgainstRealKeyProducers:
    def it_drops_only_the_old_hash_row_of_a_real_gremlin_key(self, tmp_path: Path) -> None:
        file_path = 'src/pkg/mod.py'
        gremlin_id = collect_gremlins(SOURCE, file_path)[0][0].gremlin_id
        old_hash, current_hash = 'old-hash', ContentHasher().hash_string(SOURCE)
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(gremlin_id, old_hash, {'t.py': 'h'}, RESULT)  # type: ignore[arg-type]
            cache.cache_result(gremlin_id, current_hash, {'t.py': 'h'}, RESULT)  # type: ignore[arg-type]

            cache.prune_stale_sources({gremlin_file_prefix(file_path): {current_hash}})

            assert cache.get_cached_result(gremlin_id, old_hash, {'t.py': 'h'}) is None
            assert cache.get_cached_result(gremlin_id, current_hash, {'t.py': 'h'}) == RESULT
