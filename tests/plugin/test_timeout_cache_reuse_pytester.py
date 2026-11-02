"""A warm cache survives a mutant-timeout change that cannot alter its verdicts (#567)."""

from __future__ import annotations

import pytest

SOURCE = 'def add(a, b):\n    return a + b\n'
TEST = 'from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'


def _run(pytester: pytest.Pytester, timeout: int, *extra: str) -> str:
    result = pytester.runpytest_subprocess(
        '--gremlins',
        '--gremlin-targets=calc.py',
        '--gremlin-cache',
        f'--gremlin-mutant-timeout={timeout}',
        *extra,
    )
    return result.stdout.str()


@pytest.mark.medium
class DescribeTimeoutChangeAgainstWarmCache:
    """Cold run at 30s, warm run at 31s: fast verdicts are served from the cache."""

    def it_serves_sequential_verdicts_after_a_timeout_change(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=SOURCE, test_calc=TEST)
        _run(pytester_with_markers, 30)

        warm = _run(pytester_with_markers, 31)

        assert 'cache hit (skipping)' in warm
        assert 'cache miss' not in warm
        assert 'gremlins from cache' not in warm

    def it_reports_sequential_hits_one_gremlin_at_a_time(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=SOURCE, test_calc=TEST)
        _run(pytester_with_markers, 30)

        warm = _run(pytester_with_markers, 30)

        assert 'cache hit (skipping)' in warm
        assert 'gremlins from cache' not in warm

    def it_serves_parallel_verdicts_after_a_timeout_change(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=SOURCE, test_calc=TEST)
        _run(pytester_with_markers, 30, '--gremlin-parallel')

        warm = _run(pytester_with_markers, 31, '--gremlin-parallel')

        assert ' 0 to test' in warm
        assert ' 0 gremlins from cache' not in warm

    def it_serves_batch_verdicts_after_a_timeout_change(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(calc=SOURCE, test_calc=TEST)
        _run(pytester_with_markers, 30, '--gremlin-batch')

        warm = _run(pytester_with_markers, 31, '--gremlin-batch')

        assert ' 0 to test' in warm
        assert ' 0 gremlins from cache' not in warm
