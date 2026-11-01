"""Stop early when gremlin runs, which start in the rootdir, cannot resolve what the session resolved (#686, #690).

The session may be started somewhere other than the rootdir (``cd sub && pytest``, ``--rootdir``, ``-c``).
Gremlin runs always start in the rootdir.  Two things the session resolved against its own directory then fail
in every gremlin run, so every gremlin would score ERROR:

* a relative ``@file`` in ``addopts`` or ``PYTEST_ADDOPTS`` that exists only relative to the session directory;
* node ids that do not name their test file when resolved from the rootdir.

Each check fires only on those failures; a layout whose gremlin runs resolve the same things the session did is
left alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_gremlins.argument_files import read_argument_file

if TYPE_CHECKING:
    from collections.abc import (
        Iterable,
        Sequence,
    )
    from pathlib import Path

_ARGUMENT_FILE_PREFIX = '@'
_MAX_SHOWN_NODE_IDS = 3


def argument_files_only_the_session_can_read(
    args: Sequence[str], session_dir: Path, rootdir: Path, files_being_read: tuple[Path, ...] = ()
) -> list[str]:
    """Return the ``@file`` arguments in ``args`` that resolve from ``session_dir`` but not from ``rootdir``.

    Nested ``@file`` arguments are followed through the file the session read.  A file that exists from both
    directories is not reported, whatever each holds.  A file the session cannot read is not reported either:
    pytest rejected it before any gremlin run could start.
    """
    unreadable_from_rootdir: list[str] = []
    for arg in args:
        if not arg.startswith(_ARGUMENT_FILE_PREFIX):
            continue
        name = arg[len(_ARGUMENT_FILE_PREFIX) :]
        session_file = session_dir / name
        if session_file in files_being_read:
            continue
        lines = read_argument_file(session_file)
        if lines is None:
            continue
        if read_argument_file(rootdir / name) is None:
            unreadable_from_rootdir.append(arg)
        unreadable_from_rootdir.extend(
            argument_files_only_the_session_can_read(lines, session_dir, rootdir, (*files_being_read, session_file))
        )
    return list(dict.fromkeys(unreadable_from_rootdir))


def argument_file_mismatch_message(files: Sequence[str], session_dir: Path, rootdir: Path) -> str:
    """Return the one error shown instead of an ERROR for every gremlin when ``files`` cannot be read."""
    return (
        f'pytest-gremlins: gremlin runs start in the rootdir {rootdir}, but this session started in {session_dir} '
        f'and addopts or PYTEST_ADDOPTS names {", ".join(files)} by a relative path that exists only from '
        f'{session_dir}. Every gremlin run would fail to read it and score ERROR, so no gremlin was run. '
        f'To fix it, run pytest from {rootdir} or name the file with an absolute path.'
    )


def node_ids_that_do_not_resolve(rootdir: Path, tests: Iterable[tuple[Path, str]]) -> list[str]:
    """Return the node ids of ``tests`` whose file part, resolved from ``rootdir``, is not the test's own file.

    ``tests`` pairs each collected test's file with the node id gremlin runs are given for it.  A test outside
    the rootdir gets a node id with an empty file part, which resolves to the rootdir itself.
    """
    return [node_id for test_file, node_id in tests if not _node_id_names(test_file, rootdir, node_id)]


def _node_id_names(test_file: Path, rootdir: Path, node_id: str) -> bool:
    file_part = node_id.split('::', maxsplit=1)[0]
    try:
        return bool(file_part) and (rootdir / file_part).samefile(test_file)
    except OSError:
        return False


def node_id_mismatch_message(unresolved: Sequence[str], rootdir: Path) -> str:
    """Return the one error shown instead of an ERROR for every gremlin when no node id resolves."""
    shown = ', '.join(unresolved[:_MAX_SHOWN_NODE_IDS])
    return (
        f'pytest-gremlins: gremlin runs start in the rootdir {rootdir}, but none of the {len(unresolved)} collected '
        f'tests has a node id that names its file from there (for example {shown}), so no gremlin could run a test '
        f'and no gremlin was run. This happens when --rootdir or -c puts the rootdir below the tests, or when the '
        f'tests lie outside the rootdir. To fix it, drop --rootdir, or point -c or --rootdir at the project root '
        f'that contains the tests.'
    )
