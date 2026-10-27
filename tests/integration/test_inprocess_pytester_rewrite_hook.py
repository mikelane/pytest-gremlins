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

_INNER_TEST = """
        from mypkg.core_impl import positive

        def test_positive():
            assert positive(1)
            assert not positive(0)
"""

_OUTER_HEADER = """
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / 'src'
REGISTER_CONFTEST = 'import pytest\\npytest.register_assert_rewrite("mypkg.core_impl")\\n'
"""

_PYTHON_FILES_INI = "pytester.makeini('[pytest]\\npython_files = test_*.py *_impl.py\\n')"


def _outer_tests(setup: str, run: str) -> str:
    return (
        _OUTER_HEADER
        + f"""

@pytest.mark.medium
def test_inner_session_catches_a_broken_positive(pytester, monkeypatch):
    pytester.syspathinsert(SRC)
    {setup}
    pytester.makepyfile(test_inner=\'\'\'{_INNER_TEST}\'\'\')
    {run}
"""
    )


_OUTER_TESTS = _outer_tests(
    _PYTHON_FILES_INI, "pytester.runpytest_inprocess('-p', 'no:cacheprovider').assert_outcomes(passed=1)"
)
_INLINE_RUN_TESTS = _outer_tests(
    _PYTHON_FILES_INI, "pytester.inline_run('-p', 'no:cacheprovider').assertoutcome(passed=1)"
)
_REGISTER_ASSERT_REWRITE_TESTS = _outer_tests(
    'pytester.makeconftest(REGISTER_CONFTEST)',
    "pytester.runpytest_inprocess('-p', 'no:cacheprovider').assert_outcomes(passed=1)",
)
_AUTOLOAD_DISABLED_TESTS = _outer_tests(
    _PYTHON_FILES_INI + "\n    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')",
    "pytester.runpytest_inprocess('-p', 'no:cacheprovider').assert_outcomes(passed=1)",
)
_GREMLINS_BLOCKED_TESTS = _outer_tests(
    _PYTHON_FILES_INI,
    "pytester.runpytest_inprocess('-p', 'no:cacheprovider', '-p', 'no:gremlins').assert_outcomes(passed=1)",
)
_PLUGIN_ARG_TESTS = _outer_tests(
    'pass',
    "pytester.runpytest_inprocess('-p', 'no:cacheprovider', '-p', 'mypkg.core_impl').assert_outcomes(passed=1)",
)
_PYTEST_PLUGINS_ENV_TESTS = _outer_tests(
    "monkeypatch.setenv('PYTEST_PLUGINS', 'mypkg.core_impl')",
    "pytester.runpytest_inprocess('-p', 'no:cacheprovider').assert_outcomes(passed=1)",
)


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeInProcessPytesterRewriteHook:
    """A gremlin a test catches inside an in-process pytester run is zapped, not reported as a survivor."""

    def _outcome(self, pytester: pytest.Pytester, outer_tests: str) -> tuple[int, int]:
        pytester.makeconftest(_OUTER_CONFTEST)
        pytester.makeini('[pytest]\npythonpath = src\n')
        package = pytester.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core_impl.py').write_text(_POSITIVE)
        pytester.mkdir('tests').joinpath('test_outer.py').write_text(outer_tests)

        result = pytester.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        output = result.stdout.str()
        return _count(output, 'Zapped'), _count(output, 'Survived')

    @pytest.mark.parametrize(
        'outer_tests',
        [
            pytest.param(_OUTER_TESTS, id='python_files-target'),
            pytest.param(_INLINE_RUN_TESTS, id='python_files-target-inline_run'),
            pytest.param(_REGISTER_ASSERT_REWRITE_TESTS, id='register_assert_rewrite-target'),
        ],
    )
    def it_zaps_a_target_first_imported_in_the_inner_session(
        self, pytester_with_markers: pytest.Pytester, outer_tests: str
    ) -> None:
        assert self._outcome(pytester_with_markers, outer_tests) == (2, 0)

    @pytest.mark.parametrize(
        'outer_tests',
        [
            pytest.param(_AUTOLOAD_DISABLED_TESTS, id='plugin-autoload-disabled'),
            pytest.param(_GREMLINS_BLOCKED_TESTS, id='gremlins-plugin-blocked'),
            pytest.param(_PLUGIN_ARG_TESTS, id='target-loaded-with-dash-p'),
            pytest.param(_PYTEST_PLUGINS_ENV_TESTS, id='target-loaded-through-PYTEST_PLUGINS'),
        ],
    )
    def it_reports_survivors_when_the_inner_session_does_not_load_the_gremlins_plugin(
        self, pytester_with_markers: pytest.Pytester, outer_tests: str
    ) -> None:
        """Documented limitation (docs/guide/troubleshooting.md): the finder cannot be re-fronted."""
        assert self._outcome(pytester_with_markers, outer_tests) == (0, 2)
