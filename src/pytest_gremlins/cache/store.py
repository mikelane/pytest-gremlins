"""SQLite-based result cache for incremental analysis.

The ResultStore persists gremlin test results keyed by content hashes.
This enables instant cache lookups for unchanged code, dramatically
reducing repeat run times.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path


class ResultStore:
    """SQLite-backed cache for gremlin test results.

    Stores results as JSON blobs indexed by content-based cache keys.
    Keys are typically composed of source file hash + test file hash +
    gremlin definition.

    Example:
        >>> store = ResultStore(Path('.gremlins_cache/results.db'))
        >>> store.put('abc123', {'status': 'zapped', 'killing_test': 'test_foo'})
        >>> store.get('abc123')
        {'status': 'zapped', 'killing_test': 'test_foo'}
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the result store.

        Args:
            db_path: Path to the SQLite database file. Parent directories
                     will be created if they don't exist.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the results table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                cache_key TEXT PRIMARY KEY,
                result_json TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve a cached result by key.

        Args:
            cache_key: The content-based cache key.

        Returns:
            The cached result dictionary, or None if not found.
        """
        cursor = self._conn.execute(
            'SELECT result_json FROM results WHERE cache_key = ?',
            (cache_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result: dict[str, Any] = json.loads(row[0])
        return result

    def put(self, cache_key: str, result: dict[str, Any]) -> None:
        """Store a result in the cache.

        Args:
            cache_key: The content-based cache key.
            result: The result dictionary to cache.
        """
        result_json = json.dumps(result)
        self._conn.execute(
            'INSERT OR REPLACE INTO results (cache_key, result_json) VALUES (?, ?)',
            (cache_key, result_json),
        )
        self._conn.commit()

    def delete(self, cache_key: str) -> None:
        """Remove a result from the cache.

        Args:
            cache_key: The cache key to remove.
        """
        self._conn.execute('DELETE FROM results WHERE cache_key = ?', (cache_key,))
        self._conn.commit()

    def delete_by_prefix(self, prefix: str) -> None:
        """Remove all results with keys matching a prefix.

        Useful for invalidating all gremlins in a specific file when
        that file's content changes.

        Args:
            prefix: The key prefix to match. All keys starting with
                    this prefix will be deleted.
        """
        self._conn.execute(
            'DELETE FROM results WHERE cache_key LIKE ?',
            (prefix + '%',),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._conn.execute('DELETE FROM results')
        self._conn.commit()

    def has(self, cache_key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            cache_key: The cache key to check.

        Returns:
            True if the key exists, False otherwise.
        """
        cursor = self._conn.execute(
            'SELECT 1 FROM results WHERE cache_key = ?',
            (cache_key,),
        )
        return cursor.fetchone() is not None

    def keys(self) -> list[str]:
        """Get all cache keys.

        Returns:
            List of all cache keys currently stored.
        """
        cursor = self._conn.execute('SELECT cache_key FROM results')
        return [row[0] for row in cursor.fetchall()]

    def count(self) -> int:
        """Get the number of cached entries.

        Returns:
            Total count of cached results.
        """
        cursor = self._conn.execute('SELECT COUNT(*) FROM results')
        count: int = cursor.fetchone()[0]
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> ResultStore:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit - closes the connection."""
        self.close()
