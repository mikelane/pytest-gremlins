"""A target first imported inside an in-process pytester run is still instrumented (#615).

``pytester.runpytest()`` and ``inline_run()`` call ``pytest.main`` again inside the test process. That inner
session installs a fresh assertion-rewrite hook at the front of ``sys.meta_path`` with no ``FinderFronter`` of
its own, so a target the hook claims (a ``python_files`` match here) could be served by the hook and never
instrumented.
"""

from __future__ import annotations

import re

import pytest

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_POSITIVE = """
def positive(n):
    return n > 0
"""

_OUTER_CONFTEST = """
import pytest

pytest_plugins = ['pytester']


def pytest_configure(config):
    config.addinivalue_line('markers', 'medium: medium test')
"""

_OUTER_TESTS = """
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / 'src'


@pytest.mark.medium
def test_inner_session_catches_a_broken_positive(pytester):
    pytester.syspathinsert(SRC)
    pytester.makeini('[pytest]\\npython_files = test_*.py *_impl.py\\n')
    pytester.makepyfile(
        test_inner='''
        from mypkg.core_impl import positive

        def test_positive():
            assert positive(1)
            assert not positive(0)
        '''
    )
    result = pytester.runpytest_inprocess('-p', 'no:cacheprovider')
    result.assert_outcomes(passed=1)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeInProcessPytesterRewriteHook:
    """A gremlin a test catches inside an in-process pytester run is zapped, not reported as a survivor."""

    def it_zaps_a_python_files_target_first_imported_in_the_inner_session(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeconftest(_OUTER_CONFTEST)
        pytester_with_markers.makeini('[pytest]\npythonpath = src\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core_impl.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_outer.py').write_text(_OUTER_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        output = result.stdout.str()
        assert (_count(output, 'Zapped'), _count(output, 'Survived')) == (2, 0)
