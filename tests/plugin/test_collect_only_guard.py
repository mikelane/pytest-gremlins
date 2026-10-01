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
    return collect_only_project.runpytest_subprocess('--gremlins', '--collect-only', '-p', 'no:test_categories')


@pytest.fixture
def xdist_collect_only_run(collect_only_project: pytest.Pytester) -> pytest.RunResult:
    return collect_only_project.runpytest_subprocess(
        '--gremlins', '--collect-only', '-p', 'xdist', '-n', '2', '-p', 'no:test_categories'
    )


@pytest.mark.medium
class DescribeCollectOnlyGuard:
    def it_emits_only_node_ids_under_quiet_collect_only(self, collect_only_project: pytest.Pytester) -> None:
        collect_only_project.makeini('[pytest]\naddopts = --gremlins\n')
        result = collect_only_project.runpytest_subprocess('--collect-only', '-q', '-p', 'no:test_categories')
        assert SKIP_NOTICE not in result.stdout.str()

    def it_prints_the_skip_message(self, collect_only_run: pytest.RunResult) -> None:
        collect_only_run.stderr.fnmatch_lines([SKIP_NOTICE])

    def it_skips_the_mutation_report(self, collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, collect_only_run: pytest.RunResult) -> None:
        assert 'Gremlin 1/' not in collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, collect_only_run: pytest.RunResult) -> None:
        assert collect_only_run.ret == pytest.ExitCode.OK


@pytest.mark.medium
class DescribeCollectOnlyGuardUnderXdist:
    def it_prints_the_skip_message_exactly_once(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.stderr.str().count(SKIP_NOTICE) == 1

    def it_skips_the_mutation_report(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in xdist_collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'Starting' not in xdist_collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.ret == pytest.ExitCode.OK
