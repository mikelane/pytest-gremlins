"""Tests for cache key correctness.

This test documents a bug where cache keys don't include test names,
only test hashes. This means renaming a test file without changing
its content would NOT invalidate the cache.
"""

from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache


@pytest.mark.small
class TestCacheKeyIncludesTestNames:
    """Cache key must include test names, not just hashes."""

    def test_different_test_names_same_hash_produces_different_keys(self, tmp_path: Path) -> None:
        """Different test names with same hash value produce different cache keys.

        BUG: If a test file is renamed but content unchanged, the cache key
        should change because the test that covers this gremlin has changed.

        Example scenario:
        - test_foo.py covers gremlin G1
        - Rename test_foo.py to test_bar.py (same content)
        - Cache should miss because covering tests changed

        Current behavior: Cache incorrectly hits because only hash values
        are used, not test file names.
        """
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            # Same gremlin, same source, same test HASH but different test NAME
            key_with_test_foo = cache._build_cache_key(
                gremlin_id='gremlin_1',
                source_hash='source_hash_abc',
                test_hashes={'test_foo': 'identical_hash'},
            )
            key_with_test_bar = cache._build_cache_key(
                gremlin_id='gremlin_1',
                source_hash='source_hash_abc',
                test_hashes={'test_bar': 'identical_hash'},  # Different name, same hash
            )

        # These keys SHOULD be different because the test covering this gremlin changed
        # Even though the test content is the same, the test NAME changed
        assert key_with_test_foo != key_with_test_bar, (
            'Cache keys must differ when test names differ, even if hashes are same. '
            f'Got same key: {key_with_test_foo}'
        )
