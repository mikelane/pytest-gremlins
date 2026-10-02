"""Unit tests for the baseline-health gate in ``pytest_sessionfinish`` (issues #534, #540)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _skip_mutation_unless_baseline_is_green,
)

SKIP_PREFIX = 'pytest-gremlins: skipping mutation testing because '
NON_TEST_CHECK_NOTE = (
    'pytest-gremlins: baseline tests all passed; the non-zero exit came from a non-test check '
    '(e.g. --cov-fail-under), so mutation testing continues\n'
)


@pytest.mark.small
class DescribeSkipMutationUnlessBaselineIsGreen:
    def it_proceeds_silently_when_the_baseline_is_green(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.OK)

        assert (skipped, gremlin_session.enabled, capsys.readouterr().err) == (False, True, '')

    @pytest.mark.parametrize(
        ('exitstatus', 'failed_reports', 'expected_reason'),
        [
            (pytest.ExitCode.TESTS_FAILED, 2, '2 baseline test(s) failed; mutation scores need a passing suite'),
            (pytest.ExitCode.INTERRUPTED, 0, 'the baseline test session was interrupted; rerun it to completion first'),
            (pytest.ExitCode.USAGE_ERROR, 0, 'pytest reported a usage error (exit 4)'),
            (pytest.ExitCode.NO_TESTS_COLLECTED, 0, 'no tests were collected'),
            (pytest.ExitCode.INTERNAL_ERROR, 0, 'the baseline run ended with exit code 3'),
            (7, 0, 'the baseline run ended with exit code 7'),
        ],
    )
    def it_skips_and_names_the_reason_for_every_non_green_status(
        self,
        capsys: pytest.CaptureFixture[str],
        exitstatus: int,
        failed_reports: int,
        expected_reason: str,
    ) -> None:
        gremlin_session = GremlinSession(enabled=True, baseline_failed_reports=failed_reports)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, exitstatus)

        assert (skipped, gremlin_session.enabled) == (True, False)
        assert capsys.readouterr().err == f'{SKIP_PREFIX}{expected_reason}\n'

    def it_names_collection_errors_ahead_of_the_exit_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True, collection_errors=3)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.INTERRUPTED)

        assert (skipped, gremlin_session.enabled) == (True, False)
        assert '(3 error(s))' in capsys.readouterr().err

    def it_skips_a_stopped_baseline_even_when_the_exit_status_is_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True, baseline_aborted=True)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.OK)

        assert (skipped, gremlin_session.enabled) == (True, False)
        assert capsys.readouterr().err == f'{SKIP_PREFIX}the baseline test session was stopped early (pytest.exit)\n'

    def it_skips_a_stopped_baseline_with_a_failure_status_but_no_failed_tests(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gremlin_session = GremlinSession(enabled=True, baseline_aborted=True)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.TESTS_FAILED)

        assert skipped is True
        assert capsys.readouterr().err == f'{SKIP_PREFIX}the baseline test session was stopped early (pytest.exit)\n'

    def it_proceeds_with_a_note_when_only_a_non_test_check_failed_the_run(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gremlin_session = GremlinSession(enabled=True, baseline_failed_reports=0)

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.TESTS_FAILED)

        assert (skipped, gremlin_session.enabled) == (False, True)
        assert capsys.readouterr().err == NON_TEST_CHECK_NOTE
