"""A gremlin is scored by the module the import system really loads, not by a name we guessed (#597).

The subprocess finder asks the rest of ``sys.meta_path`` what a name resolves to and instruments the
result when its file is a target. These cases are the ones no name guessed from ``sys.path`` can get right:
a finder that serves a package from a directory on no ``sys.path`` entry, one file imported under two names,
and a virtualenv-like directory inside the project.
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

_POSITIVE = """
def positive(n):
    return n > 0
"""

_POSITIVE_AND_NEGATIVE = """
def positive(n):
    return n > 0


def negative(n):
    return n < 0
"""

_EDITABLE_FINDER_CONFTEST = """
import importlib.machinery
from pathlib import Path
import sys

STORE = Path(__file__).parent / 'store'


class StoreFinder:
    # Serves packages from a directory that is on no sys.path entry, as an editable install's finder does.
    def find_spec(self, fullname, path=None, target=None):
        if '.' in fullname:
            return None
        return importlib.machinery.PathFinder.find_spec(fullname, [str(STORE)])


sys.meta_path.append(StoreFinder())
"""

_EDITABLE_TESTS = """
from editpkg.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_TESTS_BY_ROOT_NAME = """
from a.util.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_TESTS_BY_NESTED_NAME = """
from util.core import negative


def test_negative():
    assert negative(-1)
    assert not negative(0)
"""

_STALE_COPY = """
def positive(n):
    return True
"""

_SRC_TESTS = """
from mypkg.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""


_SYMLINK_ALIAS_TESTS = """
from mypkg.alias import positive as aliased_positive
from mypkg.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)


def test_aliased_positive():
    assert aliased_positive(1)
    assert not aliased_positive(0)
"""


_CORE_TESTS = """
from mypkg.core import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _verdicts(output: str) -> tuple[int, int, int]:
    return _count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeOriginResolvedModuleNames:
    """Whatever name the tests import a target under, the gremlins in its file are scored there."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_zaps_a_package_served_by_a_meta_path_finder_from_outside_sys_path(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makeconftest(_EDITABLE_FINDER_CONFTEST)
        package = pytester_with_markers.mkdir('store').joinpath('editpkg')
        package.mkdir()
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_edit.py').write_text(_EDITABLE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=store/editpkg', *_EXECUTION_MODES[mode]
        )

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    @pytest.mark.parametrize('mode', ['default', 'xdist'])
    def it_zaps_a_file_that_the_tests_import_under_two_names(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = . a\n')
        package = pytester_with_markers.path / 'a' / 'util'
        package.mkdir(parents=True)
        package.parent.joinpath('__init__.py').write_text('')
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE_AND_NEGATIVE)
        tests = pytester_with_markers.mkdir('tests')
        tests.joinpath('test_root_name.py').write_text(_TESTS_BY_ROOT_NAME)
        tests.joinpath('test_nested_name.py').write_text(_TESTS_BY_NESTED_NAME)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=a/util/core.py', *_EXECUTION_MODES[mode]
        )

        assert _verdicts(result.stdout.str()) == (4, 0, 0)

    def it_zaps_every_gremlin_when_a_target_module_is_a_symlink_to_another_target(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE)
        try:
            package.joinpath('alias.py').symlink_to('core.py')
        except OSError:
            pytest.skip('this platform cannot create symlinks')
        pytester_with_markers.mkdir('tests').joinpath('test_core.py').write_text(_SYMLINK_ALIAS_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_zaps_a_target_the_tests_import_through_a_differently_named_symlink_outside_the_targets(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src vendor\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE)
        vendor = pytester_with_markers.mkdir('vendor')
        try:
            vendor.joinpath('thing.py').symlink_to(package / 'core.py')
        except OSError:
            pytest.skip('this platform cannot create symlinks')
        pytester_with_markers.mkdir('tests').joinpath('test_thing.py').write_text(
            _CORE_TESTS.replace('from mypkg.core import', 'from thing import')
        )

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_zaps_a_target_the_import_system_spells_with_different_case_than_the_disk(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = Src\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        if not pytester_with_markers.path.joinpath('Src').exists():
            pytest.skip('this filesystem is case-sensitive, so "Src" is not the directory "src"')
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_core.py').write_text(_CORE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_names_modules_the_same_when_a_virtualenv_lives_inside_the_project(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        site_packages = pytester_with_markers.path / '.venv' / 'lib' / 'python3' / 'site-packages'
        stale = site_packages / 'mypkg'
        stale.mkdir(parents=True)
        stale.joinpath('__init__.py').write_text('')
        stale.joinpath('core.py').write_text(_STALE_COPY)
        pytester_with_markers.makeini('[pytest]\npythonpath = src .venv/lib/python3/site-packages\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_core.py').write_text(_SRC_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)
