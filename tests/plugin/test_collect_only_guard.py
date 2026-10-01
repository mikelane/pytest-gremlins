"""End-to-end pytester tests for ``--gremlins --collect-only``.

Collection-only runs must never start the mutation phase: no instrumentation,
no coverage pre-scan, no gremlin execution.
"""

from __future__ import annotations

import pytest

SKIP_NOTICE = 'pytest-gremlins: --collect-only detected, skipping mutation testing'


@pytest.fixture
def collect_only_project(pytester: pytest.Pytester) -> pytest.Pytester:
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
    return pytester


@pytest.fixture
def collect_only_run(collect_only_project: pytest.Pytester) -> pytest.RunResult:
    return collect_only_project.runpytest('--gremlins', '--collect-only')


@pytest.fixture
def xdist_collect_only_run(collect_only_project: pytest.Pytester) -> pytest.RunResult:
    return collect_only_project.runpytest('--gremlins', '--collect-only', '-p', 'xdist', '-n', '2')


@pytest.mark.medium
class DescribeCollectOnlyGuard:
    def it_prints_the_skip_message(self, collect_only_run: pytest.RunResult) -> None:
        collect_only_run.stdout.fnmatch_lines([SKIP_NOTICE])

    def it_skips_the_mutation_report(self, collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, collect_only_run: pytest.RunResult) -> None:
        assert 'Starting' not in collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, collect_only_run: pytest.RunResult) -> None:
        assert collect_only_run.ret == pytest.ExitCode.OK


@pytest.mark.medium
class DescribeCollectOnlyGuardUnderXdist:
    def it_prints_the_skip_message_exactly_once(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.stdout.str().count(SKIP_NOTICE) == 1

    def it_skips_the_mutation_report(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in xdist_collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'Starting' not in xdist_collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.ret == pytest.ExitCode.OK
