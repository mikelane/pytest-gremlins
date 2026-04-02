"""Tests for --gremlin-executor CLI option, _build_gremlin_module_map, and _run_mutation_testing_inprocess."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.fork_executor import ForkExecutor
from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.plugin import (
    GremlinSession,
    _build_gremlin_module_map,
    _run_mutation_testing,
    _run_mutation_testing_inprocess,
    pytest_addoption,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


def _make_gremlin(
    gremlin_id: str,
    file_path: str,
    *,
    pardoned: bool = False,
    pardon_reason: str | None = None,
) -> Gremlin:
    """Create a Gremlin with minimal valid fields for testing."""
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path=file_path,
        line_number=1,
        original_node=ast.Constant(value=True),
        mutated_node=ast.Constant(value=False),
        operator_name='BooleanNegate',
        description='negate boolean',
        pardoned=pardoned,
        pardon_reason=pardon_reason,
    )


@pytest.mark.small
class DescribeGremlinExecutorOption:
    """Tests that --gremlin-executor CLI option is registered."""

    def it_registers_gremlin_executor_option(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-executor' in added_option_names

    def it_defaults_to_auto(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert opt_kwargs['default'] == 'auto'

    def it_accepts_four_choices(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert set(opt_kwargs['choices']) == {'auto', 'subprocess', 'fork', 'inprocess'}


@pytest.mark.small
class DescribeAutoExecutorResolution:
    """Tests that 'auto' resolves to subprocess (safe default, full pipeline)."""

    def it_resolves_auto_to_subprocess(self) -> None:
        """auto always resolves to subprocess until fork supports the full pipeline."""
        mock_session = MagicMock(spec=pytest.Session)
        mock_session.config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        mock_session.config.option.gremlin_executor = 'auto'
        gremlin_session = GremlinSession(gremlins=[_make_gremlin('g1', '/project/src/pkg/mod.py')])

        with (
            patch('pytest_gremlins.plugin._get_rootdir', return_value=Path('/project/src')),
            patch('pytest_gremlins.plugin._build_test_command', return_value=['pytest']),
            patch('pytest_gremlins.plugin._run_mutation_testing_inprocess') as mock_inprocess,
        ):
            _run_mutation_testing(mock_session, gremlin_session)

        mock_inprocess.assert_not_called()


@pytest.mark.small
class DescribeBuildGremlinModuleMap:
    """Tests for _build_gremlin_module_map helper."""

    def it_maps_simple_file_to_module_name(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/mypackage/module.py')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g1': 'mypackage.module'}

    def it_maps_init_file_to_package_name(self) -> None:
        gremlin = _make_gremlin('g2', '/project/src/mypackage/__init__.py')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g2': 'mypackage'}

    def it_handles_file_outside_rootdir(self) -> None:
        gremlin = _make_gremlin('g3', '/elsewhere/module.py')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g3': 'module'}

    def it_maps_multiple_gremlins(self) -> None:
        g1 = _make_gremlin('g1', '/project/src/pkg/a.py')
        g2 = _make_gremlin('g2', '/project/src/pkg/b.py')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([g1, g2], rootdir)

        assert result == {'g1': 'pkg.a', 'g2': 'pkg.b'}

    def it_includes_pardoned_gremlins_in_map(self) -> None:
        gremlin = _make_gremlin('g4', '/project/src/pkg/c.py', pardoned=True, pardon_reason='equivalent: no-op')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g4': 'pkg.c'}

    def it_returns_empty_map_for_empty_list(self) -> None:
        result = _build_gremlin_module_map([], Path('/project/src'))

        assert result == {}

    def it_deduplicates_gremlins_in_same_file(self) -> None:
        g1 = _make_gremlin('g1', '/project/src/pkg/mod.py')
        g2 = _make_gremlin('g2', '/project/src/pkg/mod.py')
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([g1, g2], rootdir)

        assert result == {'g1': 'pkg.mod', 'g2': 'pkg.mod'}


@pytest.mark.small
class DescribeRunMutationTestingInprocess:
    """Tests for _run_mutation_testing_inprocess executor dispatch."""

    def it_uses_inprocess_executor_for_inprocess_choice(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/pkg/mod.py')
        session = GremlinSession(gremlins=[gremlin])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(
                gremlin_id='g1', status=GremlinResultStatus.ZAPPED, killing_test='test_a', execution_time_ms=5.0
            ),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor) as cls_mock:
            results = _run_mutation_testing_inprocess(
                'inprocess', session, Path('/project/src'), ['pytest', 'tests/test_a.py::test_a']
            )

        cls_mock.assert_called_once_with(timeout=30)
        assert len(results) == 1
        assert results[0].gremlin is gremlin
        assert results[0].status == GremlinResultStatus.ZAPPED
        assert results[0].killing_test == 'test_a'

    def it_uses_fork_executor_for_fork_choice(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/pkg/mod.py')
        session = GremlinSession(gremlins=[gremlin], batch_size=25)
        mock_executor = MagicMock(spec=ForkExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(gremlin_id='g1', status=GremlinResultStatus.SURVIVED, execution_time_ms=10.0),
        ]

        with patch('pytest_gremlins.plugin.ForkExecutor', return_value=mock_executor) as cls_mock:
            results = _run_mutation_testing_inprocess(
                'fork', session, Path('/project/src'), ['pytest', 'tests/test_a.py::test_a']
            )

        cls_mock.assert_called_once_with(batch_size=25, timeout=30)
        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.SURVIVED

    def it_converts_worker_results_to_gremlin_results(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/pkg/mod.py')
        session = GremlinSession(gremlins=[gremlin])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(
                gremlin_id='g1',
                status=GremlinResultStatus.ERROR,
                execution_time_ms=100.0,
                error_output='import failed',
            ),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            results = _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest'])

        assert len(results) == 1
        assert isinstance(results[0], GremlinResult)
        assert results[0].gremlin is gremlin
        assert results[0].status == GremlinResultStatus.ERROR
        assert results[0].error_output == 'import failed'
        assert results[0].execution_time_ms == 100.0

    def it_includes_pardoned_gremlins_in_results(self) -> None:
        active = _make_gremlin('g1', '/project/src/pkg/mod.py')
        pardoned = _make_gremlin('g2', '/project/src/pkg/mod.py', pardoned=True, pardon_reason='equivalent: no-op')
        session = GremlinSession(gremlins=[active, pardoned])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(
                gremlin_id='g1', status=GremlinResultStatus.ZAPPED, killing_test='test_a', execution_time_ms=5.0
            ),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            results = _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest'])

        assert len(results) == 2
        statuses = {r.gremlin.gremlin_id: r.status for r in results}
        assert statuses['g1'] == GremlinResultStatus.ZAPPED
        assert statuses['g2'] == GremlinResultStatus.PARDONED

    def it_skips_worker_results_with_unknown_gremlin_id(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/pkg/mod.py')
        session = GremlinSession(gremlins=[gremlin])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(
                gremlin_id='g1', status=GremlinResultStatus.ZAPPED, killing_test='test_a', execution_time_ms=5.0
            ),
            WorkerResult(gremlin_id='unknown', status=GremlinResultStatus.SURVIVED, execution_time_ms=1.0),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            results = _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest'])

        assert len(results) == 1
        assert results[0].gremlin.gremlin_id == 'g1'

    def it_extracts_test_specs_from_base_command(self) -> None:
        gremlin = _make_gremlin('g1', '/project/src/pkg/mod.py')
        session = GremlinSession(gremlins=[gremlin])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(gremlin_id='g1', status=GremlinResultStatus.SURVIVED, execution_time_ms=1.0),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            _run_mutation_testing_inprocess(
                'inprocess',
                session,
                Path('/project/src'),
                ['pytest', '-x', 'tests/test_a.py::test_one', 'tests/test_b.py::TestClass::test_two'],
            )

        mock_executor.execute.assert_called_once()
        call_args = mock_executor.execute.call_args
        test_specs = call_args[0][2] if len(call_args[0]) > 2 else call_args.kwargs.get('test_specs', [])
        assert test_specs == ['tests/test_a.py::test_one', 'tests/test_b.py::TestClass::test_two']

    def it_excludes_pardoned_gremlins_from_executor(self) -> None:
        active = _make_gremlin('g1', '/project/src/pkg/mod.py')
        pardoned = _make_gremlin('g2', '/project/src/pkg/mod.py', pardoned=True)
        session = GremlinSession(gremlins=[active, pardoned])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = [
            WorkerResult(
                gremlin_id='g1', status=GremlinResultStatus.ZAPPED, killing_test='test_a', execution_time_ms=5.0
            ),
        ]

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest'])

        call_args = mock_executor.execute.call_args
        gremlin_ids = call_args[0][0] if call_args[0] else call_args.kwargs.get('gremlin_ids', [])
        assert gremlin_ids == ['g1']

    def it_handles_empty_gremlin_list(self) -> None:
        session = GremlinSession(gremlins=[])
        mock_executor = MagicMock(spec=InProcessExecutor)
        mock_executor.execute.return_value = []

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=mock_executor):
            results = _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest'])

        assert results == []
