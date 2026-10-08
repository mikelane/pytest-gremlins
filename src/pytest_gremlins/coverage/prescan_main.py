"""Entry point of the coverage pre-scan, run as ``coverage run -m pytest_gremlins.coverage.prescan_main``.

It stands in for ``-m pytest`` so the pre-scan's node ids can travel in a file named by
``--gremlins-node-ids-file`` instead of on the command line, which Windows caps at 32,767 characters (#485).
Everything else is what ``python -m pytest`` does: the arguments are pytest's own and the exit code is
pytest's.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

import pytest

from pytest_gremlins.node_id_args import args_with_node_ids_from_file


def main(argv: Sequence[str] | None = None) -> int:
    """Run pytest on ``argv`` (default: ``sys.argv[1:]``) plus the node ids from the file it names.

    Args:
        argv: Arguments for pytest, possibly with ``--gremlins-node-ids-file=<path>``.

    Returns:
        pytest's exit code.
    """
    arguments = sys.argv[1:] if argv is None else argv
    return int(pytest.main(args_with_node_ids_from_file(arguments)))


if __name__ == '__main__':
    sys.exit(main())
