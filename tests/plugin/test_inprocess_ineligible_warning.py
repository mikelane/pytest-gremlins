"""The fork/inprocess executors warn once about tests they cannot run, and refuse to judge them."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor
from pytest_gremlins.plugin import (
    GremlinSession,
    _run_mutation_testing_inprocess,
)


def _gremlin() -> Gremlin:
    return Gremlin(
        gremlin_id='g1',
        file_path='/project/src/pkg/mod.py',
        line_number=1,
        original_node=ast.Constant(value=True),
        mutated_node=ast.Constant(value=False),
        operator_name='BooleanNegate',
        description='negate boolean',
    )


def _run(safe: frozenset[str], *specs: str) -> MagicMock:
    session = GremlinSession(gremlins=[_gremlin()], lightweight_safe_node_ids=safe)
    executor = MagicMock(spec=InProcessExecutor)
    executor.execute.return_value = []
    with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=executor):
        _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest', *specs])
    return executor


@pytest.mark.small
class DescribeInProcessIneligibleTests:
    """Ineligible selected tests are flagged to the executor and announced at startup."""

    def it_warns_with_the_count_and_the_subprocess_suggestion(self) -> None:
        with pytest.warns(UserWarning, match=r'1 of 2 selected tests.*--gremlin-executor=subprocess'):
            _run(frozenset({'t.py::test_a'}), 't.py::test_a', 't.py::test_b')

    def it_passes_the_ineligible_specs_to_the_executor(self) -> None:
        with pytest.warns(UserWarning, match='cannot run under'):
            executor = _run(frozenset({'t.py::test_a'}), 't.py::test_a', 't.py::test_b')

        assert executor.execute.call_args.kwargs['ineligible_specs'] == frozenset({'t.py::test_b'})

    def it_does_not_warn_when_every_selected_test_is_safe(self, recwarn: pytest.WarningsRecorder) -> None:
        _run(frozenset({'t.py::test_a'}), 't.py::test_a')

        assert len(recwarn) == 0


@pytest.mark.small
class DescribeInProcessTestSelection:
    """The base test command carries no node IDs, so the collected tests are what get run."""

    def it_runs_the_collected_tests_when_the_command_names_none(self) -> None:
        session = GremlinSession(
            gremlins=[_gremlin()],
            test_node_ids={'t.py::test_a': 't.py::test_a'},
            lightweight_safe_node_ids=frozenset({'t.py::test_a'}),
        )
        executor = MagicMock(spec=InProcessExecutor)
        executor.execute.return_value = []

        with patch('pytest_gremlins.plugin.InProcessExecutor', return_value=executor):
            _run_mutation_testing_inprocess('inprocess', session, Path('/project/src'), ['pytest', '-x'])

        assert executor.execute.call_args.args[2] == ['t.py::test_a']
