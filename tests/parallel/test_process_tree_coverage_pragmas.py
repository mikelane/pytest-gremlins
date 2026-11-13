"""The ``# pragma: posix cover`` markers in process_tree hide only code that Windows never runs (#975).

On Windows the CI coverage step excludes ``# pragma: posix cover``. A pragma on a line that Windows executes, such as a
``sys.platform`` guard that Windows evaluates and skips, hides measured Windows code from the Windows report.
"""

from __future__ import annotations

from pathlib import Path

from coverage.parser import PythonParser
import pytest

import pytest_gremlins.process_tree as process_tree_module

POSIX_PRAGMA = '# pragma: posix cover'


@pytest.mark.medium
class DescribePosixCoverPragma:
    @pytest.mark.parametrize(
        'windows_statement',
        [
            # _register and _unregister call _tell_watchdog on every platform; Windows runs its guard and returns.
            "if sys.platform == 'win32':\n        return\n    died_pid",
            # _terminate_tree: Windows evaluates the guard, skips its body and runs the finally.
            "if sys.platform != 'win32':\n            _signal_group(process, signal.SIGTERM)",
            # _abandon_pipes: Windows evaluates the guard, then waits for the process.
            "if sys.platform != 'win32':\n        for pipe in",
        ],
    )
    def it_leaves_statements_windows_executes_measured_on_windows(self, windows_statement: str) -> None:
        path = Path(process_tree_module.__file__)
        source = path.read_text(encoding='utf-8')
        first_line = source[: source.index(windows_statement)].count('\n') + 1
        parser = PythonParser(text=source, filename=str(path), exclude=POSIX_PRAGMA)
        parser.parse_source()

        assert first_line not in parser.excluded
