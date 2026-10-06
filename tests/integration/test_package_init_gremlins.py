"""Gremlins planted in a package ``__init__.py`` are activated and scored like any other module's (#591).

``pkg/__init__.py`` used to be registered under the name ``pkg.__init__``, which nothing imports, so the
instrumented package was never served and every gremlin in it survived whatever the tests asserted.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_PACKAGE_INIT = """
def over(n):
    return n > 10
"""

_PACKAGE_INIT_TESTS = """
import pkg


def test_over():
    assert pkg.over(11)
    assert not pkg.over(10)
"""

_INIT_WITH_RELATIVE_IMPORT = """
from .core import positive


def over(n):
    return n > 10
"""

_CORE = """
def positive(n):
    return n > 0
"""

_INIT_AND_CORE_TESTS = """
import pkg
import pkg.core


def test_init_gremlins_are_caught():
    assert pkg.over(11)
    assert not pkg.over(10)


def test_core_gremlins_are_caught():
    assert pkg.core.positive(1)
    assert not pkg.core.positive(0)


def test_relative_import_resolves_to_the_submodule():
    assert pkg.positive is pkg.core.positive
"""

_NESTED_INIT = """
def under(n):
    return n < 5
"""

_NESTED_TESTS = """
from pkg.sub import under


def test_under():
    assert under(4)
    assert not under(5)
"""

_INIT_READING_ITS_LOCATION = """
from pathlib import Path

LIMIT = int((Path(__file__).parent / 'limit.txt').read_text())
SEARCH_PATH = list(__path__)


def over(n):
    return n > LIMIT
"""

_LOCATION_TESTS = """
import os

import pkg

LOG = '__LOG__'


def test_over():
    row = (
        os.environ.get('ACTIVE_GREMLIN', 'NONE'),
        pkg.__file__,
        pkg.__spec__.origin,
        ','.join(pkg.SEARCH_PATH),
        ','.join(pkg.__spec__.submodule_search_locations),
        pkg.__package__,
    )
    with open(LOG, 'a') as handle:
        handle.write('\\t'.join(row) + '\\n')
    assert pkg.over(11)
    assert not pkg.over(10)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _write_package(root: Path, name: str, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = root / name / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


@pytest.mark.medium
class DescribePackageInitGremlins:
    """A gremlin in ``__init__.py`` that a test catches is ZAPPED, not SURVIVED."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_zaps_a_comparison_gremlin_the_tests_catch(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        pytester_with_markers.mkpydir('pkg').joinpath('__init__.py').write_text(_PACKAGE_INIT)
        pytester_with_markers.makepyfile(test_pkg=_PACKAGE_INIT_TESTS)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=pkg', *_EXECUTION_MODES[mode]
        )
        output = result.stdout.str()

        assert (_count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')) == (2, 0, 0)

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_scores_the_package_and_its_submodule_with_a_relative_import(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        _write_package(pytester_with_markers.path, 'pkg', {'__init__.py': _INIT_WITH_RELATIVE_IMPORT, 'core.py': _CORE})
        pytester_with_markers.makepyfile(test_pkg=_INIT_AND_CORE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=pkg', *_EXECUTION_MODES[mode]
        )
        output = result.stdout.str()

        assert (_count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')) == (4, 0, 0)

    def it_still_imports_an_uninstrumented_submodule_of_an_instrumented_package(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        _write_package(pytester_with_markers.path, 'pkg', {'__init__.py': _INIT_WITH_RELATIVE_IMPORT, 'core.py': _CORE})
        pytester_with_markers.makepyfile(test_pkg=_INIT_AND_CORE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=pkg/__init__.py')
        output = result.stdout.str()

        assert (_count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')) == (2, 0, 0)

    def it_zaps_a_gremlin_in_a_nested_package_init(self, pytester_with_markers: pytest.Pytester) -> None:
        _write_package(pytester_with_markers.path, 'pkg', {'__init__.py': '', 'sub/__init__.py': _NESTED_INIT})
        pytester_with_markers.makepyfile(test_pkg=_NESTED_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=pkg')
        output = result.stdout.str()

        assert (_count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')) == (2, 0, 0)

    def it_zaps_a_gremlin_in_a_src_layout_package_init(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src\n')
        _write_package(pytester_with_markers.path / 'src', 'pkg', {'__init__.py': _PACKAGE_INIT})
        pytester_with_markers.makepyfile(test_pkg=_PACKAGE_INIT_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/pkg')
        output = result.stdout.str()

        assert (_count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')) == (2, 0, 0)

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_gives_the_instrumented_package_its_real_location_attributes(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        log = pytester_with_markers.path / 'ran.log'
        _write_package(pytester_with_markers.path, 'pkg', {'__init__.py': _INIT_READING_ITS_LOCATION})
        pytester_with_markers.path.joinpath('pkg', 'limit.txt').write_text('10')
        pytester_with_markers.makepyfile(test_pkg=_LOCATION_TESTS.replace('__LOG__', log.as_posix()))

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=pkg', *_EXECUTION_MODES[mode]
        )
        rows = [line.split('\t') for line in log.read_text().splitlines()]
        mutant_rows = [row for row in rows if row[0] != 'NONE']
        init_file = str(pytester_with_markers.path / 'pkg' / '__init__.py')
        package_dir = str(pytester_with_markers.path / 'pkg')

        assert _count(result.stdout.str(), 'Error') == 0
        assert mutant_rows
        assert {tuple(row[1:]) for row in mutant_rows} == {(init_file, init_file, package_dir, package_dir, 'pkg')}
