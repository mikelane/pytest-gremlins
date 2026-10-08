"""Read the node ids a parent left in a file for this process to run (issue #485).

See :mod:`pytest_gremlins.node_id_file` for the writing half and the reason the ids travel in a file.

This file is copied verbatim into the generated bootstrap script, which cannot import pytest-gremlins and
must start fast. Keep it standard-library only (``json`` alone) and free of ``from __future__`` imports.
"""

from collections.abc import Sequence
import json

NODE_IDS_FILE_OPTION = '--gremlins-node-ids-file'
_NODE_IDS_FILE_PREFIX = f'{NODE_IDS_FILE_OPTION}='


def args_with_node_ids_from_file(args: Sequence[str]) -> list[str]:
    """Return ``args`` without the node ids file option, followed by the ids that file holds.

    Args:
        args: Arguments for ``pytest.main``, possibly holding ``--gremlins-node-ids-file=<path>``.

    Returns:
        The arguments to give ``pytest.main``.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If the file does not hold a JSON list of strings.

    Example:
        >>> args_with_node_ids_from_file(['-x', 'a.py::t'])
        ['-x', 'a.py::t']
    """
    args_without_option = [argument for argument in args if not argument.startswith(_NODE_IDS_FILE_PREFIX)]
    node_ids: list[str] = []
    for argument in args:
        if argument.startswith(_NODE_IDS_FILE_PREFIX):
            node_ids.extend(_read_node_ids(argument[len(_NODE_IDS_FILE_PREFIX) :]))
    return [*args_without_option, *node_ids]


def _read_node_ids(path: str) -> list[str]:
    with open(path, encoding='utf-8') as node_ids_file:  # noqa: PTH123 - the child avoids importing pathlib
        try:
            node_ids = json.load(node_ids_file)
        except ValueError as decode_error:
            raise ValueError(f'node id file {path} is not valid JSON: {decode_error}') from decode_error
    if not isinstance(node_ids, list) or not all(isinstance(node_id, str) for node_id in node_ids):
        raise ValueError(f'node id file {path} does not hold a list of node id strings')
    return node_ids
