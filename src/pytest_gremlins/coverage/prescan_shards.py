"""Divide the coverage pre-scan's node ids among serial shard processes (issue #527).

Tests are split by file, not one by one, for two reasons. Module- and class-scoped fixtures, and the import
and collection of a test module, are then paid for in one shard instead of several. And a file's tests keep
the order they would have in a single process. Files are handed out largest first to the shard with the fewest
tests so far, which keeps the shards close in size when the suite has many files. A suite that is mostly one
huge file cannot be split any finer, and gets one busy shard.
"""

from __future__ import annotations

from collections.abc import Sequence

FILE_SEPARATOR = '::'


def split_into_shards(node_ids: Sequence[str], shard_count: int) -> list[list[str]]:
    """Divide ``node_ids`` among at most ``shard_count`` shards, keeping each test file whole.

    Args:
        node_ids: Pytest node ids in the order a single process would run them.
        shard_count: The most shards wanted; fewer come back when there are fewer files.

    Returns:
        Non-empty shards, each holding whole files in the order the files first appear in ``node_ids``.
        Every node id is in exactly one shard.

    Example:
        >>> split_into_shards(['a.py::t1', 'a.py::t2', 'b.py::t1'], 2)
        [['a.py::t1', 'a.py::t2'], ['b.py::t1']]
    """
    ids_by_file = _group_by_file(node_ids)
    shard_count = max(1, min(shard_count, len(ids_by_file)))
    shard_files: list[list[str]] = [[] for _ in range(shard_count)]
    shard_sizes = [0] * shard_count
    for file, ids in sorted(ids_by_file.items(), key=lambda item: -len(item[1])):
        lightest = shard_sizes.index(min(shard_sizes))
        shard_files[lightest].append(file)
        shard_sizes[lightest] += len(ids)
    first_seen = {file: position for position, file in enumerate(ids_by_file)}
    return [
        [node_id for file in sorted(files, key=first_seen.__getitem__) for node_id in ids_by_file[file]]
        for files in shard_files
        if files
    ]


def _group_by_file(node_ids: Sequence[str]) -> dict[str, list[str]]:
    """Map each test file to its node ids, files in order of first appearance."""
    ids_by_file: dict[str, list[str]] = {}
    for node_id in node_ids:
        ids_by_file.setdefault(node_id.split(FILE_SEPARATOR, 1)[0], []).append(node_id)
    return ids_by_file
