"""Gremlin runs inherit pytest-rerunfailures settings, so a flaky test cannot falsely zap a mutant (refs #546).

The flaky test fails on its first call in every fresh process and passes on the rerun.  The
baseline passes only because it is rerun.  If a per-gremlin subprocess did not rerun it, the flake
would fail the subprocess and every gremlin would be zapped, including the ones the test cannot
catch.  The test is deliberately weak: it leaves some mutants of ``classify`` alive.
"""

from __future__ import annotations

import pytest
from rerun_samples import (
    FLAKY_STRONG_TEST,
    FLAKY_WEAK_TEST,
    GREMLIN_ARGS,
    SAMPLE,
    run_gremlins,
    survivor_count,
    verdicts,
    write_flaky_project,
)


@pytest.mark.medium
class DescribeRerunOptionsOnTheCommandLine:
    @pytest.mark.parametrize(
        'mode_args',
        [(), ('--gremlin-parallel', '--gremlin-workers=2'), ('--gremlin-batch',)],
        ids=['sequential', 'parallel', 'batch'],
    )
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, mode_args: tuple[str, ...]
    ) -> None:
        result = run_gremlins(pytester_with_markers, '--reruns', '2', *mode_args)

        assert survivor_count(result.stdout.str()) > 0

    def it_still_zaps_mutants_that_a_flaky_test_catches_on_every_attempt(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        result = run_gremlins(pytester_with_markers, '--reruns', '2', tests=FLAKY_STRONG_TEST)

        counts = verdicts(result.stdout.str())
        assert counts['Survived'] == 0
        assert counts['Zapped'] > 0

    def it_reaches_the_gremlin_runs_of_an_xdist_session(self, pytester_with_markers: pytest.Pytester) -> None:
        result = run_gremlins(pytester_with_markers, '--reruns', '2', '-n', '2')

        assert survivor_count(result.stdout.str()) > 0

    def it_reaches_the_gremlin_runs_from_an_argument_file(self, pytester_with_markers: pytest.Pytester) -> None:
        (pytester_with_markers.path / 'rerun.args').write_text('--reruns=2\n', encoding='utf-8')

        result = run_gremlins(pytester_with_markers, '@rerun.args')

        assert survivor_count(result.stdout.str()) > 0

    def it_reaches_the_gremlin_runs_from_an_ini_override(self, pytester_with_markers: pytest.Pytester) -> None:
        result = run_gremlins(pytester_with_markers, '-o', 'reruns=2')

        assert survivor_count(result.stdout.str()) > 0

    def it_wins_over_a_rerun_count_in_addopts(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = --reruns 0\n')

        result = run_gremlins(pytester_with_markers, '--reruns', '2')

        assert survivor_count(result.stdout.str()) > 0


@pytest.mark.medium
class DescribeRerunOptionsInAddopts:
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = --reruns 2\n')

        result = run_gremlins(pytester_with_markers)

        assert survivor_count(result.stdout.str()) > 0


@pytest.mark.medium
class DescribeRerunIniKeysInAConfigFileNamedOnTheCommandLine:
    """Gremlin runs never read the ``-c`` file, so the settings it holds must be forwarded to them."""

    @pytest.mark.parametrize('config_args', [('-c', 'ci.ini'), ('--config-file=ci.ini',)])
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, config_args: tuple[str, ...]
    ) -> None:
        (pytester_with_markers.path / 'ci.ini').write_text('[pytest]\nreruns = 2\n', encoding='utf-8')

        result = run_gremlins(pytester_with_markers, *config_args)

        assert 'needed a rerun' in result.stderr.str()
        assert survivor_count(result.stdout.str()) > 0

    def it_lets_a_rerun_count_on_the_command_line_win_over_the_file(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.ini').write_text('[pytest]\nreruns = 0\n', encoding='utf-8')

        result = run_gremlins(pytester_with_markers, '-c', 'ci.ini', '--reruns', '2')

        assert survivor_count(result.stdout.str()) > 0

    def it_forwards_a_list_setting_whose_pattern_contains_a_space(self, pytester_with_markers: pytest.Pytester) -> None:
        # Only a failure matching ``only_rerun`` is rerun; if the list were mangled on the way, nothing would be.
        (pytester_with_markers.path / 'ci.ini').write_text(
            '[pytest]\nreruns = 2\nonly_rerun =\n    no such failure\n    AssertionError\n', encoding='utf-8'
        )

        result = run_gremlins(pytester_with_markers, '-c', 'ci.ini')

        assert survivor_count(result.stdout.str()) > 0

    def it_does_not_zap_everything_when_a_pattern_in_the_list_never_matches(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.ini').write_text(
            '[pytest]\nreruns = 2\nonly_rerun = no such failure\n', encoding='utf-8'
        )

        result = run_gremlins(pytester_with_markers, '-c', 'ci.ini')

        # The baseline itself fails when the flake is not rerun, so mutation testing never starts.
        assert verdicts(result.stdout.str())['Zapped'] == 0


@pytest.mark.medium
class DescribeNumericRerunSettingsInNativeToml:
    def it_runs_gremlins_without_an_internal_error_when_reruns_is_a_toml_integer(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        steady_test = "from sample import classify\n\n\ndef test_big():\n    assert classify(11) == 'big'\n"
        write_flaky_project(pytester_with_markers, steady_test)
        pytester_with_markers.makefile('.toml', pyproject='[tool.pytest]\nreruns = 2\n')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS)

        assert 'INTERNALERROR' not in result.stdout.str()
        assert verdicts(result.stdout.str())['Zapped'] > 0


@pytest.mark.medium
class DescribeProjectsWithoutRerunOptions:
    def it_completes_without_rerun_flags_or_a_warning(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=FLAKY_WEAK_TEST.replace('len(calls) > 1', 'True'))

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS)

        assert result.ret == 0
        assert '--reruns' not in result.stderr.str()
        assert 'needed a rerun' not in result.stderr.str()


@pytest.mark.medium
class DescribeBaselineRerunWarning:
    def it_warns_once_naming_the_test_that_needed_a_rerun(self, pytester_with_markers: pytest.Pytester) -> None:
        result = run_gremlins(pytester_with_markers, '--reruns', '2')

        warnings = [line for line in result.stderr.lines if 'needed a rerun' in line]

        assert len(warnings) == 1
        assert 'test_sample.py::test_big' in warnings[0]

    def it_stays_silent_when_no_baseline_test_was_rerun(self, pytester_with_markers: pytest.Pytester) -> None:
        result = run_gremlins(
            pytester_with_markers, '--reruns', '2', tests=FLAKY_STRONG_TEST.replace('len(calls) > 1', 'True')
        )

        # The zaps prove the run reached mutation testing, so the missing warning is not a crash.
        assert verdicts(result.stdout.str())['Zapped'] > 0
        assert 'needed a rerun' not in result.stderr.str()
