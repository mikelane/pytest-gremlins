"""Module names stay importable when pytest itself puts a test directory on ``sys.path`` (#597 follow-up).

With ``--import-mode=prepend`` (the default) or ``append``, a test file in a directory without an
``__init__.py`` has that directory inserted into ``sys.path`` during collection. When source files sit in
the same directory, any naming scheme that derives module names from ``sys.path`` names them by their
short name (``core``) even when the tests import them by their full name (``mypkg.sub.core``). The
instrumented code never loads and every gremlin the tests catch is reported SURVIVED.

The xdist controller does not collect, so it never sees those inserted entries and would name the same
files differently from the other execution modes: one project, two different scores. Resolving
instrumented files by the origin the import system loads keeps every mode on the same name.
"""

from __future__ import annotations

import re

import pytest

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
    'xdist': ('-n', '2'),
}

_CORE = """
def positive(n):
    return n > 0
"""

_FULL_NAME_TESTS = """
from mypkg.sub.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_SHORT_NAME_TESTS = """
from tool import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_NESTED_ENTRY_TESTS = """
from a.util.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _verdicts(output: str) -> tuple[int, int, int]:
    return _count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')


def _write_colocated_package(pytester: pytest.Pytester) -> None:
    package = pytester.path / 'mypkg'
    sub = package / 'sub'
    sub.mkdir(parents=True)
    package.joinpath('__init__.py').write_text('')
    sub.joinpath('core.py').write_text(_CORE)
    sub.joinpath('test_core.py').write_text(_FULL_NAME_TESTS)


@pytest.mark.medium
class DescribeColocatedModuleNames:
    """A caught gremlin is ZAPPED whatever directory pytest inserts into ``sys.path`` to reach the tests."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_zaps_a_colocated_module_the_tests_import_by_its_full_name(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        _write_colocated_package(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=mypkg/sub/core.py', *_EXECUTION_MODES[mode]
        )

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    @pytest.mark.parametrize('import_mode', ['prepend', 'append'])
    def it_zaps_a_colocated_module_on_a_dot_pythonpath_whatever_the_import_mode(
        self, pytester_with_markers: pytest.Pytester, import_mode: str
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = .\n')
        _write_colocated_package(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, f'--import-mode={import_mode}', '--gremlin-targets=mypkg/sub/core.py'
        )

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_zaps_a_package_the_tests_import_through_the_outer_of_two_nested_pythonpath_entries(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = . a\n')
        package = pytester_with_markers.path / 'a' / 'util'
        package.mkdir(parents=True)
        package.parent.joinpath('__init__.py').write_text('')
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_CORE)
        pytester_with_markers.mkdir('tests').joinpath('test_core.py').write_text(_NESTED_ENTRY_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=a/util')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_scores_a_module_beside_its_tests_the_same_with_and_without_xdist(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        scripts = pytester_with_markers.mkdir('scripts')
        scripts.joinpath('tool.py').write_text(_CORE)
        scripts.joinpath('test_tool.py').write_text(_SHORT_NAME_TESTS)
        targets = '--gremlin-targets=scripts/tool.py'

        serial = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, targets)
        distributed = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, targets, '-n', '2')

        # Pinning the score keeps two runs that both crash before reporting from agreeing on (0, 0, 0).
        assert (_verdicts(serial.stdout.str()), _verdicts(distributed.stdout.str())) == ((2, 0, 0), (2, 0, 0))
