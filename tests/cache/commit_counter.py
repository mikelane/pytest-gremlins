"""Helper that counts SQLite commits so tests assert behaviour instead of wall-clock time."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def record_commits(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every COMMIT statement run on connections opened after this call.

    Hooks the public ``sqlite3.connect`` entry point, so tests never reach into
    the private connection of the object under test. Commits issued while the
    object opens its database (schema creation) are recorded too; call
    ``commits.clear()`` after construction to count only later activity.

    Returns:
        A list that grows by one entry per commit.
    """
    commits: list[str] = []
    real_connect = sqlite3.connect

    def record(statement: str) -> None:
        if statement.strip().upper() == 'COMMIT':
            commits.append(statement)

    def connect_and_record(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)  # type: ignore[call-overload]
        connection.set_trace_callback(record)
        return connection  # type: ignore[no-any-return]

    monkeypatch.setattr(sqlite3, 'connect', connect_and_record)
    return commits
