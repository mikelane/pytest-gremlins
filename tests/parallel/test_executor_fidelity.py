"""In-process and fork executors must never judge a test they cannot run faithfully."""

from __future__ import annotations

from collections.abc import Iterator
import sys
import types

import pytest

from pytest_gremlins.parallel.fork_executor import ForkExecutor
from pytest_gremlins.parallel.inprocess_executor import (
    InProcessExecutor,
    _run_test_spec,
    _TestOutcome,
)
from pytest_gremlins.reporting.results import GremlinResultStatus

MODULE_NAME = '_executor_fidelity_tests'
SOURCE = """
calls = []

def test_plain():
    calls.append('plain')

def test_fails():
    raise AssertionError('caught')

async def test_async():
    calls.append('async')
"""


@pytest.fixture
def test_module() -> Iterator[types.ModuleType]:
    module = types.ModuleType(MODULE_NAME)
    exec(compile(SOURCE, MODULE_NAME, 'exec'), module.__dict__)  # noqa: S102
    sys.modules[MODULE_NAME] = module
    yield module
    sys.modules.pop(MODULE_NAME, None)


def _spec(name: str) -> str:
    return f'{MODULE_NAME}::{name}'


@pytest.mark.small
@pytest.mark.usefixtures('test_module')
class DescribeRunTestSpecCoroutines:
    """A callable returning a coroutine was never executed, so it is not a verdict."""

    def it_reports_error_for_a_coroutine_returning_test(self) -> None:
        assert _run_test_spec(_spec('test_async')) is _TestOutcome.ERROR

    def it_does_not_run_the_coroutine_body(self, test_module: types.ModuleType) -> None:
        _run_test_spec(_spec('test_async'))

        assert test_module.calls == []  # type: ignore[attr-defined]

    def it_still_passes_a_plain_test(self) -> None:
        assert _run_test_spec(_spec('test_plain')) is _TestOutcome.PASSED


@pytest.mark.small
@pytest.mark.usefixtures('test_module')
class DescribeInProcessExecutorIneligibleTests:
    """Tests outside the safe set are never called directly."""

    def it_reports_error_without_calling_an_ineligible_test(self, test_module: types.ModuleType) -> None:
        spec = _spec('test_plain')

        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [spec], ineligible_specs=frozenset({spec}))

        assert results[0].status == GremlinResultStatus.ERROR
        assert test_module.calls == []  # type: ignore[attr-defined]

    def it_names_the_test_and_the_subprocess_executor_in_the_error(self) -> None:
        spec = _spec('test_plain')

        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [spec], ineligible_specs=frozenset({spec}))

        assert spec in results[0].error_output
        assert '--gremlin-executor=subprocess' in results[0].error_output

    def it_reports_error_when_any_selected_test_is_ineligible(self) -> None:
        eligible, ineligible = _spec('test_fails'), _spec('test_plain')

        results = InProcessExecutor().execute(
            ['g1'], {'g1': MODULE_NAME}, [eligible, ineligible], ineligible_specs=frozenset({ineligible})
        )

        assert results[0].status == GremlinResultStatus.ERROR

    def it_reports_error_for_a_coroutine_test_even_if_not_flagged(self) -> None:
        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [_spec('test_async')])

        assert results[0].status == GremlinResultStatus.ERROR

    def it_still_zaps_with_an_eligible_failing_test(self) -> None:
        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [_spec('test_fails')])

        assert results[0].status == GremlinResultStatus.ZAPPED


@pytest.mark.small
class DescribeInProcessExecutorWithoutTests:
    """Running no tests proves nothing, so it must never read as a surviving gremlin."""

    def it_reports_error_when_no_test_specs_are_supplied(self) -> None:
        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [])

        assert results[0].status == GremlinResultStatus.ERROR

    def it_says_that_no_tests_were_run(self) -> None:
        results = InProcessExecutor().execute(['g1'], {'g1': MODULE_NAME}, [])

        assert 'no tests' in results[0].error_output.lower()


@pytest.mark.medium
@pytest.mark.usefixtures('test_module')
class DescribeForkExecutorIneligibleTests:
    """The fork executor forwards the ineligible set to the in-process executor."""

    def it_reports_error_without_calling_an_ineligible_test(self) -> None:
        spec = _spec('test_plain')

        results = ForkExecutor(batch_size=1).execute(
            ['g1'], {'g1': MODULE_NAME}, [spec], ineligible_specs=frozenset({spec})
        )

        assert results[0].status == GremlinResultStatus.ERROR
        assert '--gremlin-executor=subprocess' in results[0].error_output
