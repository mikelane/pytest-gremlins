"""Gremlins in packages on a non-``src`` ``pythonpath`` entry are activated and scored (#597).

With ``pythonpath = a``, tests import ``a/util/core.py`` as ``util.core``. It used to be registered as
``a.util.core``, a name nothing imports, so every gremlin in it survived whatever the tests asserted.
"""

from __future__ import annotations

import re

import pytest

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
    'xdist': ('-n', '2'),
}

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_UTIL_INIT = """
from .core import positive


def over(n):
    return n > 10
"""

_UTIL_CORE = """
def positive(n):
    return n > 0
"""

_UTIL_TESTS = """
import util
import util.core


def test_init_gremlins_are_caught():
    assert util.over(11)
    assert not util.over(10)


def test_core_gremlins_are_caught():
    assert util.core.positive(1)
    assert not util.core.positive(0)
"""

_LONE_MODULE = """
def small(n):
    return n < 5
"""

_LONE_MODULE_TESTS = """
from lone import small


def test_small():
    assert small(4)
    assert not small(5)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _verdicts(output: str) -> tuple[int, int, int]:
    return _count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')


def _write_util_package(pytester: pytest.Pytester, entry: str) -> None:
    package = pytester.path / entry / 'util'
    package.mkdir(parents=True)
    package.joinpath('__init__.py').write_text(_UTIL_INIT)
    package.joinpath('core.py').write_text(_UTIL_CORE)
    pytester.mkdir('tests').joinpath('test_util.py').write_text(_UTIL_TESTS)


@pytest.mark.medium
class DescribePythonpathModuleNames:
    """A gremlin that a test catches is ZAPPED when its package lives under a ``pythonpath`` entry."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_zaps_gremlins_in_a_package_on_a_non_src_pythonpath_entry(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = a\n')
        _write_util_package(pytester_with_markers, 'a')

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-targets=a', *_EXECUTION_MODES[mode]
        )

        assert _verdicts(result.stdout.str()) == (4, 0, 0)

    def it_zaps_gremlins_in_a_package_on_a_nested_pythonpath_entry(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = libs/vendor\n')
        _write_util_package(pytester_with_markers, 'libs/vendor')

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=libs')

        assert _verdicts(result.stdout.str()) == (4, 0, 0)

    def it_zaps_a_plain_module_on_a_pythonpath_entry(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = a\n')
        pytester_with_markers.mkdir('a').joinpath('lone.py').write_text(_LONE_MODULE)
        pytester_with_markers.mkdir('tests').joinpath('test_lone.py').write_text(_LONE_MODULE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=a')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)
