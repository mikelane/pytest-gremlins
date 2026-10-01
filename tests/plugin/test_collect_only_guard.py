"""End-to-end pytester tests for ``--gremlins --collect-only``.

Collection-only runs validate configuration but must never start the mutation
phase: no cache setup, no instrumentation, no coverage pre-scan, no gremlin execution.
"""

from __future__ import annotations

import pytest

_SKIP_NOTICE = 'pytest-gremlins: --collect-only detected, skipping mutation testing'
_NO_CATEGORIES = ('-p', 'no:test_categories')


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
cache = true
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
    return collect_only_project.runpytest_subprocess('--gremlins', '--collect-only', *_NO_CATEGORIES)


@pytest.fixture
def xdist_collect_only_run(collect_only_project: pytest.Pytester) -> pytest.RunResult:
    return collect_only_project.runpytest_subprocess(
        '--gremlins', '--collect-only', '-p', 'xdist', '-n', '2', *_NO_CATEGORIES
    )


@pytest.mark.medium
class DescribeCollectOnlyGuard:
    def it_prints_the_skip_notice_to_stderr(self, collect_only_run: pytest.RunResult) -> None:
        collect_only_run.stderr.fnmatch_lines([_SKIP_NOTICE])

    def it_keeps_stdout_limited_to_node_ids_under_quiet_collect_only(
        self, collect_only_project: pytest.Pytester
    ) -> None:
        collect_only_project.makeini('[pytest]\naddopts = --gremlins\n')
        result = collect_only_project.runpytest_subprocess('--collect-only', '-q', *_NO_CATEGORIES)
        result.stdout.fnmatch_lines(['test_target.py::test_zero_case'])
        assert _SKIP_NOTICE not in result.stdout.str()
        result.stderr.fnmatch_lines([_SKIP_NOTICE])

    def it_skips_the_mutation_report(self, collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, collect_only_run: pytest.RunResult) -> None:
        assert 'Gremlin 1/' not in collect_only_run.stdout.str()
        assert 'pytest-gremlins: Starting' not in collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, collect_only_run: pytest.RunResult) -> None:
        assert collect_only_run.ret == pytest.ExitCode.OK

    def it_skips_cache_setup(self, collect_only_project: pytest.Pytester) -> None:
        collect_only_project.runpytest_subprocess('--gremlins', '--collect-only', *_NO_CATEGORIES)
        assert not (collect_only_project.path / '.gremlins_cache').exists()


@pytest.mark.medium
class DescribeFullRunSetup:
    def it_creates_the_cache_directory_without_collect_only(self, collect_only_project: pytest.Pytester) -> None:
        collect_only_project.runpytest_subprocess('--gremlins', *_NO_CATEGORIES)
        assert (collect_only_project.path / '.gremlins_cache').exists()


@pytest.mark.medium
class DescribeCollectOnlyGuardUnderXdist:
    def it_prints_the_skip_notice_to_stderr_exactly_once(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.stderr.str().count(_SKIP_NOTICE) == 1

    def it_skips_the_mutation_report(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in xdist_collect_only_run.stdout.str()

    def it_skips_gremlin_execution(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert 'Gremlin 1/' not in xdist_collect_only_run.stdout.str()
        assert 'pytest-gremlins: Starting' not in xdist_collect_only_run.stdout.str()

    def it_exits_with_the_normal_collect_only_status(self, xdist_collect_only_run: pytest.RunResult) -> None:
        assert xdist_collect_only_run.ret == pytest.ExitCode.OK


@pytest.mark.medium
class DescribeCollectOnlyConfigValidation:
    def it_rejects_an_invalid_toml_value(self, collect_only_project: pytest.Pytester) -> None:
        collect_only_project.makepyprojecttoml('[tool.pytest-gremlins]\ncache = "yes"\n')
        result = collect_only_project.runpytest_subprocess('--gremlins', '--collect-only', *_NO_CATEGORIES)
        assert result.ret != pytest.ExitCode.OK
        assert 'must be a boolean' in result.stdout.str() + result.stderr.str()

    def it_rejects_an_out_of_range_max_pardons_pct(self, collect_only_project: pytest.Pytester) -> None:
        result = collect_only_project.runpytest_subprocess(
            '--gremlins', '--collect-only', '--gremlin-max-pardons-pct=150', *_NO_CATEGORIES
        )
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert '--gremlin-max-pardons-pct must be between 0 and 100' in result.stdout.str() + result.stderr.str()

    def it_still_skips_mutation_for_a_valid_config(self, collect_only_run: pytest.RunResult) -> None:
        assert 'mutation report' not in collect_only_run.stdout.str()
