"""Adversarial QA (#891): pytester loaded under its module path still retires #615 verdicts."""

from __future__ import annotations

import pytest

GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', '--gremlin-cache')
COLD = 'Cache: 0 hits, 2 misses (0% hit rate)'
TARGET_WITH_COMPARISON = 'def limit(x):\n    return x > 41\n'
TEST_WITH_COMPARISON = 'from target import limit\n\n\ndef test_limit():\n    assert limit(42)\n'


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makepyfile(target=TARGET_WITH_COMPARISON, test_target=TEST_WITH_COMPARISON)
    return pytester


@pytest.mark.medium
class DescribePytesterLoadedByModulePath:
    def it_misses_the_cache_once_when_pytester_is_loaded_with_p_and_its_module_path(
        self, project: pytest.Pytester
    ) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, '-p', '_pytest.pytester').stdout.fnmatch_lines([COLD])
