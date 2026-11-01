"""Expansion of ``@file`` command-line arguments the way pytest's parser reads them (issues #546, #688)."""

from __future__ import annotations

import locale
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_ARGUMENT_FILE_PREFIX = '@'

# argparse opens an ``@file`` with the locale encoding (strict) before Python 3.12 and with the filesystem
# encoding and error handler from 3.12 on.
_ARGPARSE_READS_LOCALE_ENCODING = sys.version_info < (3, 12)


def _argparse_file_decoding() -> tuple[str, str]:
    """Return the encoding and error handler the running Python's argparse reads an ``@file`` with."""
    if _ARGPARSE_READS_LOCALE_ENCODING:
        return locale.getpreferredencoding(False), 'strict'
    return sys.getfilesystemencoding(), sys.getfilesystemencodeerrors()


def expand_argument_files(args: Sequence[str], base_dir: Path, files_being_read: tuple[Path, ...] = ()) -> list[str]:
    """Replace each ``@file`` argument with the lines of that file, the way pytest's parser does.

    A file is decoded the way the running Python's argparse decodes it: with the locale encoding, strictly,
    before Python 3.12, and with the filesystem encoding and error handler from 3.12 on.
    A file that cannot be read or decoded, or that is already being read further up (a cycle), contributes
    nothing.
    pytest itself rejects an unreadable ``@file`` as a usage error and recurses without end on a cycle,
    so a file pytest read from ``base_dir`` can fail to read here only if it changed after pytest parsed it.
    ``base_dir`` may differ from the directory pytest read from (the plugin passes the rootdir, while pytest
    expanded from the session's current directory), so a read can also fail for that reason.
    Either way the unreadable file is skipped.
    """
    expanded: list[str] = []
    for arg in args:
        if not arg.startswith(_ARGUMENT_FILE_PREFIX):
            expanded.append(arg)
            continue
        argument_file = base_dir / arg[len(_ARGUMENT_FILE_PREFIX) :]
        if argument_file in files_being_read:
            continue
        try:
            encoding, errors = _argparse_file_decoding()
            lines = argument_file.read_text(encoding=encoding, errors=errors).splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        expanded.extend(expand_argument_files(lines, base_dir, (*files_being_read, argument_file)))
    return expanded
