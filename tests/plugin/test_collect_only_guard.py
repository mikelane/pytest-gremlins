"""End-to-end pytester tests for ``--gremlins --collect-only``.

Collection-only runs must never start the mutation phase: no instrumentation,
no coverage pre-scan, no gremlin execution.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def collect_only_run(pytester: pytest.Pytester) -> pytest.RunResult:
    pytester.makepyfile(
        target=("def classify(value: int) -> str:\n    if value == 0:\n        return 'zero'\n    return 'nonzero'\n"),
    )
    pytester.makepyfile(
        test_target=(
            'import pytest\n'
            'from target import classify\n'
            '\n'
            '@pytest.mark.small\n'
            'def test_zero_case():\n'
            "    assert classify(0) == 'zero'\n"
        ),
    )
    pytester.makepyprojecttoml(
        """
[tool.pytest-gremlins]
paths = ["target.py"]
"""
    )
    pytester.makeconftest(
        """
def pytest_configure(config):
    config.addinivalue_line('markers', 'small: fast unit tests')
"""
    )
    return pytester.runpytest('--gremlins', '--collect-only')


@pytest.mark.medium
class DescribeCollectOnlyGuard:
    def it_prints_the_skip_message(self, collect_only_run: pytest.RunResult) -> None:
        collect_only_run.stdout.fnmatch_lines(['pytest-gremlins: --collect-only detected, skipping mutation testing'])

    def it_skips_the_mutation_report(self, collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, collect_only_run: pytest.RunResult) -> None:
        assert 'Starting' not in collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, collect_only_run: pytest.RunResult) -> None:
        assert collect_only_run.ret == pytest.ExitCode.OK
