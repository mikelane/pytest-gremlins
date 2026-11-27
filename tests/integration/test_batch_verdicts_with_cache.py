"""An uninterrupted --gremlin-batch run reports the same verdicts with and without the cache (issue #979).

Batch results now reach the cache as each batch returns, so the final report must still match a run that
caches nothing and a run that tests every gremlin in its own task.
"""

from __future__ import annotations

import re

import pytest

_CALC = """
def add(a, b):
    return a + b


def is_positive(n):
    return n > 0
"""

_TESTS = """
from calc import add, is_positive


def test_add():
    assert add(2, 3) == 5


def test_is_positive():
    assert is_positive(1)
"""

_BASE_ARGS = ('--gremlins', '--gremlin-targets=calc.py', '--gremlin-operators=arithmetic,comparison,boundary')


def _verdict_counts(output: str) -> tuple[int, int]:
    zapped = re.search(r'Zapped: (\d+) gremlins', output)
    survived = re.search(r'Survived: (\d+) gremlins', output)
    assert zapped is not None
    assert survived is not None
    return int(zapped.group(1)), int(survived.group(1))


@pytest.mark.medium
class DescribeBatchVerdictsWithTheCache:
    @pytest.mark.parametrize(
        'batch_args',
        [('--gremlin-batch-size=1',), ('--gremlin-batch-size=2',), ('--gremlin-batch-size=50',)],
        ids=['one-per-batch', 'two-per-batch', 'one-batch'],
    )
    def it_reports_the_verdicts_the_sequential_run_reports(
        self, pytester_with_markers: pytest.Pytester, batch_args: tuple[str, ...]
    ) -> None:
        pytester_with_markers.makepyfile(calc=_CALC, test_calc=_TESTS)

        sequential = pytester_with_markers.runpytest_subprocess(*_BASE_ARGS, '-p', 'no:cacheprovider')
        batch = pytester_with_markers.runpytest_subprocess(
            *_BASE_ARGS, '--gremlin-batch', '--gremlin-cache', *batch_args, '-p', 'no:cacheprovider'
        )

        assert _verdict_counts(batch.stdout.str()) == _verdict_counts(sequential.stdout.str())

    def it_reports_the_same_verdicts_from_a_warm_cache(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=_CALC, test_calc=_TESTS)
        args = (*_BASE_ARGS, '--gremlin-batch', '--gremlin-batch-size=2', '--gremlin-cache', '-p', 'no:cacheprovider')

        cold = pytester_with_markers.runpytest_subprocess(*args)
        warm = pytester_with_markers.runpytest_subprocess(*args)

        assert _verdict_counts(warm.stdout.str()) == _verdict_counts(cold.stdout.str())
