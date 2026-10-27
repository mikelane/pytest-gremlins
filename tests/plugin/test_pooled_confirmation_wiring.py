"""The parallel and batch runners judge their results through ``_confirm_pooled_result`` (issue #576).

Both runners are ``# pragma: no cover``, so a reverted or mis-wired call site would pass every other
medium test. These tests drive a real tiny run in each mode and spy on the confirmation step.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

import pytest

from pytest_gremlins import plugin

if TYPE_CHECKING:
    from pytest_gremlins.plugin import GremlinSession

MUTANT_TIMEOUT_SECONDS = 17

_SAMPLE = """
def add(a, b):
    return a + b
"""

_COVERING_TEST = """
from sample import add


def test_add():
    assert add(2, 3) == 5
"""

_UNRELATED_TEST = """
def test_unrelated():
    assert True
"""

_MODES = {
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


@pytest.fixture
def confirmation_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every call to ``_confirm_pooled_result`` while still running the real confirmation."""
    calls: list[dict[str, Any]] = []
    real_confirm = plugin._confirm_pooled_result

    def spy(
        result: Any,
        test_command: list[str],
        node_ids: list[str],
        gremlin_session: GremlinSession,
        rootdir: Any,
    ) -> Any:
        calls.append(
            {
                'selected_tests': list(result.selected_tests),
                'node_ids': list(node_ids),
                'mutant_timeout': gremlin_session.mutant_timeout,
            }
        )
        return real_confirm(result, test_command, node_ids, gremlin_session, rootdir)

    monkeypatch.setattr(plugin, '_confirm_pooled_result', spy)
    return calls


@pytest.mark.medium
@pytest.mark.parametrize('mode', sorted(_MODES))
class DescribePooledRunsConfirmTheirResults:
    """Each pooled gremlin result passes through the confirmation step with its own selection and timeout."""

    def it_confirms_every_result_with_the_covering_tests_and_the_effective_timeout(
        self,
        pytester_with_markers: pytest.Pytester,
        confirmation_calls: list[dict[str, Any]],
        mode: str,
    ) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_COVERING_TEST)
        pytester_with_markers.makepyfile(test_unrelated=_UNRELATED_TEST)

        pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            f'--gremlin-mutant-timeout={MUTANT_TIMEOUT_SECONDS}',
            '-p',
            'no:cacheprovider',
            *_MODES[mode],
        )

        assert confirmation_calls
        assert {call['mutant_timeout'] for call in confirmation_calls} == {MUTANT_TIMEOUT_SECONDS}
        assert all(call['node_ids'] == ['test_sample.py::test_add'] for call in confirmation_calls)
        assert all(call['selected_tests'] == ['test_sample.py::test_add'] for call in confirmation_calls)
