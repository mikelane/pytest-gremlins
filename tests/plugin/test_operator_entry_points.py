"""End-to-end tests for third-party operators discovered through the ``pytest_gremlins.operators`` entry point.

Each test installs a real ``.dist-info`` distribution (see ``install_entry_point_dist``) and runs
``pytest --gremlins`` against a small project, so discovery goes through ``importlib.metadata``.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import textwrap

import pytest

Installer = Callable[..., Path]

UNKNOWN_OPERATOR = 'Unknown operator'

EP_CONSTANT_MODULE = textwrap.dedent(
    """
    import ast


    class EpConstantOperator:
        name = 'ep-constant'
        description = 'increments integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + 1)]


    def register(registry):
        registry.register(EpConstantOperator)
    """
)

MARKERS_CONFTEST = textwrap.dedent(
    """
    import pytest


    def pytest_configure(config):
        config.addinivalue_line('markers', 'small: fast tests')


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(items):
        for item in items:
            item.add_marker(pytest.mark.small)
    """
)

CONFTEST_SHADOW = (
    '\n\nfrom pytest_gremlins.instrumentation.transformer import get_default_registry\n'
    'import ast\n\n\n'
    'class ConftestCompare:\n'
    "    name = 'ep-constant'\n"
    "    description = 'conftest'\n\n"
    '    def can_mutate(self, node):\n        return isinstance(node, ast.Compare)\n\n'
    '    def mutate(self, node):\n'
    '        return [ast.Compare(left=node.left, ops=[ast.Gt()], comparators=node.comparators)]\n\n\n'
    "get_default_registry().register(ConftestCompare, name='ep-constant')\n"
)


TARGET = 'def limit():\n    return 41\n\n\ndef less(a, b):\n    return a < b\n'
TARGET_TEST = (
    'from target import limit, less\n\n\n'
    'def test_limit():\n    assert limit() == 41\n\n\n'
    'def test_less():\n    assert less(1, 2)\n    assert not less(2, 1)\n'
)


def _write_project(pytester: pytest.Pytester, *, conftest_extra: str = '', pyproject: str = '') -> None:
    pytester.makeconftest(MARKERS_CONFTEST + conftest_extra)
    if pyproject:
        pytester.makepyprojecttoml(pyproject)
    pytester.makepyfile(target=TARGET, test_target=TARGET_TEST)


def _operators_in_report(pytester: pytest.Pytester) -> list[tuple[str, int]]:
    report = json.loads(pytester.path.joinpath('coverage/gremlins/gremlins.json').read_text())
    return [(entry['operator'], entry['line_number']) for entry in report['results']]


def _run(pytester: pytest.Pytester, *args: str, in_process: bool = False) -> pytest.RunResult:
    runner = pytester.runpytest if in_process else pytester.runpytest_subprocess
    return runner('--gremlins', '--gremlin-targets=target.py', '--gremlin-report=json', *args)


def _output(result: pytest.RunResult) -> str:
    """Return stdout and stderr: warnings raised during configure are written to stderr."""
    return result.stdout.str() + result.stderr.str()


def _count(result: pytest.RunResult, text: str) -> int:
    return sum(text in line for line in [*result.stdout.lines, *result.stderr.lines])


@pytest.fixture
def ep_constant(install_entry_point_dist: Installer) -> None:
    install_entry_point_dist({'ep': 'ep_ops:register'}, {'ep_ops': EP_CONSTANT_MODULE})


@pytest.mark.medium
@pytest.mark.usefixtures('ep_constant')
class DescribeInstalledOperatorPackage:
    def it_produces_gremlins_from_an_installed_package(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)

        _run(pytester)

        assert 'ep-constant' in {name for name, _ in _operators_in_report(pytester)}

    def it_works_with_parallel_workers(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)

        _run(pytester, '--gremlin-workers=2')

        assert 'ep-constant' in {name for name, _ in _operators_in_report(pytester)}

    def it_works_under_xdist_without_unknown_operator_warnings(self, pytester: pytest.Pytester) -> None:
        pytest.importorskip('xdist')
        _write_project(pytester)

        result = _run(pytester, '-n', '2', '--gremlin-operators=ep-constant')

        assert 'ep-constant' in {name for name, _ in _operators_in_report(pytester)}
        assert UNKNOWN_OPERATOR not in _output(result)

    def it_accepts_the_operator_name_with_collect_only(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)

        result = _run(pytester, '--collect-only', '--gremlin-operators=ep-constant')

        assert UNKNOWN_OPERATOR not in _output(result)

    def it_selects_the_operator_on_the_command_line(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)

        result = _run(pytester, '--gremlin-operators=ep-constant')

        assert {name for name, _ in _operators_in_report(pytester)} == {'ep-constant'}
        assert UNKNOWN_OPERATOR not in _output(result)

    def it_selects_the_operator_from_pyproject(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester, pyproject="[tool.pytest-gremlins]\noperators = ['ep-constant']\n")

        _run(pytester)

        assert {name for name, _ in _operators_in_report(pytester)} == {'ep-constant'}

    def it_lets_a_root_conftest_registration_win(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        install_entry_point_dist({'ep': 'ep_ops:register'}, {'ep_ops': EP_CONSTANT_MODULE})
        _write_project(pytester, conftest_extra=CONFTEST_SHADOW)

        result = _run(pytester, '--gremlin-operators=ep-constant')

        assert {line for _, line in _operators_in_report(pytester)} == {6}
        assert _count(result, 'GremlinEntryPointWarning') >= 1
        assert "entry point 'ep'" in _output(result)

    def it_does_not_load_entry_points_without_gremlins(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester, tmp_path: Path
    ) -> None:
        sentinel = tmp_path / 'imported.flag'
        source = (
            'from pathlib import Path\n'
            f'Path({str(sentinel)!r}).write_text("x")\n\n\n'
            'def register(registry):\n    pass\n'
        )
        install_entry_point_dist({'sentinel': 'sentinel_ops:register'}, {'sentinel_ops': source})
        _write_project(pytester)

        pytester.runpytest_subprocess()

        assert not sentinel.exists()


BROKEN_MODULES = {
    'import-fails': ('missing_module_xyz:register', {}, 'missing_module_xyz'),
    'callable-raises': (
        'broken_ops:register',
        {'broken_ops': 'def register(registry):\n    raise RuntimeError("kaput")\n'},
        'kaput',
    ),
    'not-callable': ('broken_ops:register', {'broken_ops': 'register = 42\n'}, 'is not callable'),
}


@pytest.mark.medium
class DescribeBrokenEntryPoints:
    @pytest.mark.parametrize('scenario', sorted(BROKEN_MODULES))
    def it_warns_and_still_runs_built_in_operators(
        self, scenario: str, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        target, modules, detail = BROKEN_MODULES[scenario]
        install_entry_point_dist({'broken-ep': target}, modules)
        _write_project(pytester)

        result = _run(pytester)

        output = _output(result)
        assert 'GremlinEntryPointWarning' in output
        assert 'broken-ep' in output
        assert 'gremlin_ep_dist' in output
        assert detail in output
        assert _operators_in_report(pytester)

    def it_hides_the_warning_when_the_category_is_ignored(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        install_entry_point_dist({'broken-ep': 'broken_ops:register'}, {'broken_ops': 'register = 42\n'})
        _write_project(pytester)

        result = _run(pytester, '-W', 'ignore::pytest_gremlins.operators.GremlinEntryPointWarning')

        assert 'GremlinEntryPointWarning' not in _output(result)
        assert _operators_in_report(pytester)

    def it_stops_the_run_when_warnings_are_errors(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        install_entry_point_dist({'broken-ep': 'broken_ops:register'}, {'broken_ops': 'register = 42\n'})
        _write_project(pytester, pyproject='[tool.pytest.ini_options]\nfilterwarnings = ["error"]\n')

        result = _run(pytester)

        assert result.ret != 0
        assert 'GremlinEntryPointWarning' in _output(result)

    def it_warns_once_under_xdist(self, install_entry_point_dist: Installer, pytester: pytest.Pytester) -> None:
        pytest.importorskip('xdist')
        install_entry_point_dist(
            {'broken-ep': 'broken_ops:register'},
            {'broken_ops': 'def register(registry):\n    raise RuntimeError("kaput")\n'},
        )
        _write_project(pytester)

        result = _run(pytester, '-n', '2')

        assert _count(result, "entry point 'broken-ep'") == 1

    def it_discards_operators_from_a_callable_that_fails_partway(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        source = (
            EP_CONSTANT_MODULE + '\n\ndef partial(registry):\n    register(registry)\n    raise RuntimeError("late")\n'
        )
        install_entry_point_dist({'partial': 'ep_ops:partial'}, {'ep_ops': source})
        _write_project(pytester)

        result = _run(pytester, '--gremlin-operators=ep-constant,comparison')

        assert 'ep-constant' not in {name for name, _ in _operators_in_report(pytester)}
        assert f"{UNKNOWN_OPERATOR} 'ep-constant'" in _output(result)

    def it_does_not_let_an_entry_point_replace_a_built_in(
        self, install_entry_point_dist: Installer, pytester: pytest.Pytester
    ) -> None:
        source = EP_CONSTANT_MODULE.replace("name = 'ep-constant'", "name = 'comparison'")
        install_entry_point_dist({'shadow-ep': 'ep_ops:register'}, {'ep_ops': source})
        _write_project(pytester)

        result = _run(pytester, '--gremlin-operators=comparison')

        assert {line for _, line in _operators_in_report(pytester)} == {6}
        output = _output(result)
        assert "operator 'comparison'" in output
        assert 'shadow-ep' in output


@pytest.mark.medium
@pytest.mark.usefixtures('ep_constant')
class DescribeRepeatedConfigureInOneProcess:
    def it_does_not_warn_about_its_own_operators_on_a_second_run(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)

        _run(pytester, in_process=True)
        second = _run(pytester, in_process=True)

        assert 'GremlinEntryPointWarning' not in _output(second)
        assert 'ep-constant' in {name for name, _ in _operators_in_report(pytester)}

    def it_reports_a_later_runs_conftest_shadow(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)
        _run(pytester, in_process=True)
        pytester.makeconftest(MARKERS_CONFTEST + CONFTEST_SHADOW)

        result = _run(pytester, '--gremlin-operators=ep-constant', in_process=True)

        assert "entry point 'ep'" in _output(result)
        assert {line for _, line in _operators_in_report(pytester)} == {6}
