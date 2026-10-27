"""Helper that counts SQLite commits so tests assert behaviour instead of wall-clock time."""

from __future__ import annotations

import sqlite3


def count_commits(connection: sqlite3.Connection) -> list[str]:
    """Record every COMMIT statement the connection executes from now on.

    Returns:
        A list that grows by one entry per commit.
    """
    commits: list[str] = []

    def record(statement: str) -> None:
        if statement.strip().upper() == 'COMMIT':
            commits.append(statement)

    connection.set_trace_callback(record)
    return commits
