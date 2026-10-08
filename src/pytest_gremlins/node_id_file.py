"""Hand node ids to a pytest child through a file instead of its command line (issue #485).

Windows refuses to start a process whose command line exceeds 32,767 characters, and a large suite's
node ids alone can pass that. The parent writes the ids to a file and puts ``--gremlins-node-ids-file=<path>``
on the command line; the child's launcher (the gremlin bootstrap, or the coverage pre-scan launcher)
removes that option and appends the ids to the arguments it hands to ``pytest.main``. pytest therefore sees
exactly the arguments it would have seen with the ids on the command line, in the same order.

The reading half lives in :mod:`pytest_gremlins.node_id_args`, which the generated bootstrap script embeds.
"""

from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import tempfile

from pytest_gremlins.node_id_args import (
    NODE_IDS_FILE_OPTION,
    args_with_node_ids_from_file,
)

__all__ = [
    'NODE_IDS_FILE_OPTION',
    'args_with_node_ids_from_file',
    'command_with_node_ids_file',
    'write_node_ids_file',
]


def write_node_ids_file(node_ids: Sequence[str], directory: Path) -> Path:
    """Write ``node_ids`` to a file in ``directory`` named after its content, and return its path.

    Equal selections share one file, so concurrent workers that write the same selection agree on the
    path; the file appears atomically, so a reader never sees half of it.

    Args:
        node_ids: Node ids in the order pytest must receive them.
        directory: Existing directory that outlives every process reading the file.

    Returns:
        Path to the JSON file holding the node ids.

    Example:
        >>> with tempfile.TemporaryDirectory() as scratch:
        ...     json.loads(write_node_ids_file(['a.py::t'], Path(scratch)).read_text(encoding='utf-8'))
        ['a.py::t']
    """
    serialized_node_ids = json.dumps(list(node_ids))
    digest = hashlib.sha256(serialized_node_ids.encode('utf-8')).hexdigest()[:32]
    path = directory / f'node_ids_{digest}.json'
    if path.exists():
        return path
    descriptor, temporary_name = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as temporary_file:
            temporary_file.write(serialized_node_ids)
        Path(temporary_name).replace(path)
    except BaseException as write_error:
        Path(temporary_name).unlink(missing_ok=True)
        if not _lost_race_to_identical_writer(write_error, path):
            raise
    return path


def _lost_race_to_identical_writer(error: BaseException, path: Path) -> bool:
    """Whether ``error`` is Windows refusing to replace a ``path`` that an equal selection already filled."""
    return isinstance(error, PermissionError) and path.exists()


def command_with_node_ids_file(command: Sequence[str], node_ids: Sequence[str], directory: Path | None) -> list[str]:
    """Return ``command`` extended to run ``node_ids``, with the ids in a file rather than on the command line.

    Args:
        command: A command whose launcher understands ``--gremlins-node-ids-file``.
        node_ids: Node ids to run, in order. An empty sequence leaves ``command`` as it is.
        directory: Where to write the file. When there is none, the ids go on the command line.

    Returns:
        A new command; ``command`` itself is not modified.

    Example:
        >>> command_with_node_ids_file(['pytest', '-x'], ['a.py::t'], None)
        ['pytest', '-x', 'a.py::t']
    """
    if not node_ids:
        return list(command)
    if directory is None:
        return [*command, *node_ids]
    return [*command, f'{NODE_IDS_FILE_OPTION}={write_node_ids_file(node_ids, directory)}']
