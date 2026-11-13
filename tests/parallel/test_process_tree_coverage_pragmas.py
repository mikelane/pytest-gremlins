"""The ``# pragma: posix cover`` markers in process_tree hide only code that Windows never runs (#975).

On Windows the CI coverage step sets ``GREMLINS_COVERAGE_OTHER_PLATFORM=posix``, and the ``exclude_also`` entry in
``pyproject.toml`` then excludes ``# pragma: posix cover``. These tests read that real configuration through the public
``coverage.Coverage`` API. A pragma on a line that Windows executes, such as a ``sys.platform`` guard that Windows
evaluates and skips, would hide measured Windows code from the Windows report.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
import warnings

import coverage
import pytest

import pytest_gremlins.process_tree as process_tree_module

PLATFORM_VARIABLE = 'GREMLINS_COVERAGE_OTHER_PLATFORM'
POSIX_PRAGMA = '# pragma: posix cover'
PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'
PROCESS_TREE = Path(process_tree_module.__file__)


def _load_config(monkeypatch: pytest.MonkeyPatch, other_platform: str | None) -> coverage.Coverage:
    if other_platform is None:
        monkeypatch.delenv(PLATFORM_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(PLATFORM_VARIABLE, other_platform)
    return coverage.Coverage(data_file=None, config_file=str(PYPROJECT))


def _excluded_lines(cov: coverage.Coverage) -> set[int]:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # no data was collected: only the exclusion analysis is wanted
        _, _, excluded, _, _ = cov.analysis2(str(PROCESS_TREE))
    return set(excluded)


def _exclude_list(cov: coverage.Coverage) -> list[str]:
    return list(cast('list[str]', cov.get_option('report:exclude_also')))


def _line_of(snippet: str) -> int:
    source = PROCESS_TREE.read_text(encoding='utf-8')
    assert snippet in source
    return source[: source.index(snippet)].count('\n') + 1


def _lines_carrying_the_posix_pragma() -> set[int]:
    source = PROCESS_TREE.read_text(encoding='utf-8')
    return {number for number, text in enumerate(source.splitlines(), start=1) if POSIX_PRAGMA in text}


@pytest.mark.medium
class DescribePosixCoverPragma:
    @pytest.mark.parametrize(
        'windows_statement',
        [
            # _register and _unregister call _tell_watchdog on every platform; Windows runs its guard and returns.
            "if sys.platform == 'win32':\n        return\n    died_pid",
            'return\n    died_pid, start_error',
            # sigterm_cleanup: Windows evaluates the guard and returns before the handler is installed.
            "sys.platform == 'win32'\n        or threading",
            'yield\n        return\n    replaced',
            # _terminate_tree: Windows evaluates the guard, skips its body and runs the finally.
            "if sys.platform != 'win32':\n            _signal_group(process, signal.SIGTERM)",
            # _abandon_pipes: Windows evaluates the guard, then waits for the process.
            "if sys.platform != 'win32':\n        for pipe in",
            # _kill_tree: Windows runs the guard and ends the tree with taskkill.
            "if sys.platform == 'win32':\n        _taskkill_tree(process)",
            '_taskkill_tree(process)\n    else:',
            # _stop_watchdog: Windows has no watchdog, so it returns at the guard.
            'if current is None or current.owner != os.getpid():\n        return',
            'return\n    with contextlib.suppress(OSError, ValueError):  # pragma: posix cover\n        if current',
        ],
    )
    def it_leaves_statements_windows_executes_measured_on_windows(
        self, monkeypatch: pytest.MonkeyPatch, windows_statement: str
    ) -> None:
        excluded = _excluded_lines(_load_config(monkeypatch, 'posix'))

        assert _line_of(windows_statement) not in excluded

    @pytest.mark.parametrize(
        'posix_only_statement',
        [
            # The pragma on `try:` does not reach the finally clause, which Windows never gets to.
            'finally:  # pragma: posix cover\n        signal.signal(signal.SIGTERM, replaced',
            'signal.signal(signal.SIGTERM, replaced if replaced is not None',
        ],
    )
    def it_excludes_statements_windows_never_runs_on_windows(
        self, monkeypatch: pytest.MonkeyPatch, posix_only_statement: str
    ) -> None:
        excluded = _excluded_lines(_load_config(monkeypatch, 'posix'))

        assert _line_of(posix_only_statement) in excluded

    def it_adds_the_posix_pragma_to_the_exclude_list_when_measuring_on_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cov = _load_config(monkeypatch, 'posix')

        assert POSIX_PRAGMA in _exclude_list(cov)

    def it_excludes_nothing_marked_posix_when_the_platform_variable_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        excluded = _excluded_lines(_load_config(monkeypatch, None))

        assert excluded & _lines_carrying_the_posix_pragma() == set()

    def it_leaves_the_posix_pragma_out_of_the_exclude_list_when_the_platform_variable_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cov = _load_config(monkeypatch, None)

        assert POSIX_PRAGMA not in _exclude_list(cov)
