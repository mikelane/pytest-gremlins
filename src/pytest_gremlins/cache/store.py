"""SQLite-based result cache for incremental analysis.

The ResultStore persists gremlin test results keyed by content hashes.
This enables instant cache lookups for unchanged code, dramatically
reducing repeat run times.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path


logger = logging.getLogger(__name__)


class ResultStore:
    """SQLite-backed cache for gremlin test results.

    Stores results as JSON blobs indexed by content-based cache keys.
    Keys are typically composed of source file hash + test file hash +
    gremlin definition.

    Example:
        >>> from pathlib import Path
        >>> store = ResultStore(Path('.gremlins_cache/results.db'))
        >>> store.put('abc123', {'status': 'zapped', 'killing_test': 'test_foo'})
        >>> store.get('abc123')
        {'status': 'zapped', 'killing_test': 'test_foo'}
        >>> store.close()
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the result store.

        If the database file is corrupted, it will be deleted and a fresh
        database will be created. A warning will be logged in this case.

        Args:
            db_path: Path to the SQLite database file. Parent directories
                     will be created if they don't exist.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = self._open_or_recreate_db()
        self._pending_writes: list[tuple[str, str]] = []

    def _open_or_recreate_db(self) -> sqlite3.Connection:
        """Open the database, recreating it if corrupted.

        Attempts to connect to the database and initialize the schema.
        If a DatabaseError occurs (indicating corruption), the file is
        deleted and a fresh database is created.

        Returns:
            An open SQLite connection with initialized schema.
        """
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(self._db_path))
            self._init_schema_on_conn(conn)
        except sqlite3.DatabaseError:
            logger.warning(
                'Cache database corrupted at %s, recreating',
                self._db_path,
            )
            if conn is not None:  # pragma: no branch
                conn.close()
            self._db_path.unlink(missing_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            self._init_schema_on_conn(conn)
        return conn

    def _init_schema_on_conn(self, conn: sqlite3.Connection) -> None:
        """Create the results table if it doesn't exist.

        Args:
            conn: The database connection to initialize.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                cache_key TEXT PRIMARY KEY,
                result_json TEXT NOT NULL
            )
        """)
        conn.commit()

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

    def put_deferred(self, cache_key: str, result: dict[str, Any]) -> None:
        """Store a result without committing immediately.

        Results are batched and committed on flush() or close(). This is
        faster for bulk inserts as it reduces commit overhead.

        Args:
            cache_key: The content-based cache key.
            result: The result dictionary to cache.
        """
        result_json = json.dumps(result)
        self._pending_writes.append((cache_key, result_json))

    def flush(self) -> None:
        """Commit all pending deferred writes.

        This commits any results added via put_deferred() in a single
        transaction, which is much faster than individual commits.
        """
        if not self._pending_writes:
            return

        self._conn.executemany(
            'INSERT OR REPLACE INTO results (cache_key, result_json) VALUES (?, ?)',
            self._pending_writes,
        )
        self._conn.commit()
        self._pending_writes.clear()

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
        # Escape LIKE metacharacters (%, _) in the prefix to treat them as literals.
        # Use backslash as the escape character (specified in ESCAPE clause).
        escaped_prefix = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        self._conn.execute(
            "DELETE FROM results WHERE cache_key LIKE ? ESCAPE '\\'",
            (escaped_prefix + '%',),
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
        """Close the database connection.

        Flushes any pending deferred writes before closing.
        """
        self.flush()
        self._conn.close()

    def __enter__(self) -> ResultStore:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object,
    ) -> None:
        """Context manager exit - closes the connection."""
        self.close()
