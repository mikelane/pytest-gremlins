"""Unit tests for the baseline-health gate in ``pytest_sessionfinish`` (issue #534)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _skip_mutation_unless_baseline_is_green,
)


def _baseline_with_failures(tests_failed: int) -> pytest.Session:
    """A stand-in session exposing only the failure count the gate reads."""
    return cast('pytest.Session', SimpleNamespace(testsfailed=tests_failed))


@pytest.mark.small
class DescribeSkipMutationUnlessBaselineIsGreen:
    def it_proceeds_when_the_baseline_is_green(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True)

        skipped = _skip_mutation_unless_baseline_is_green(
            gremlin_session, _baseline_with_failures(0), pytest.ExitCode.OK
        )

        assert (skipped, gremlin_session.enabled, capsys.readouterr().err) == (False, True, '')

    @pytest.mark.parametrize(
        ('exitstatus', 'tests_failed', 'expected_reason'),
        [
            (pytest.ExitCode.TESTS_FAILED, 2, '2 baseline test(s) failed; mutation scores need a passing suite'),
            (pytest.ExitCode.INTERRUPTED, 0, 'the baseline test session was interrupted; rerun it to completion first'),
            (pytest.ExitCode.USAGE_ERROR, 0, 'pytest reported a usage error (exit 4)'),
            (pytest.ExitCode.NO_TESTS_COLLECTED, 0, 'no tests were collected'),
            (pytest.ExitCode.INTERNAL_ERROR, 0, 'the baseline run ended with exit code 3'),
            (7, 0, 'the baseline run ended with exit code 7'),
        ],
    )
    def it_skips_and_names_the_reason_for_every_non_ok_status(
        self,
        capsys: pytest.CaptureFixture[str],
        exitstatus: int,
        tests_failed: int,
        expected_reason: str,
    ) -> None:
        gremlin_session = GremlinSession(enabled=True)

        skipped = _skip_mutation_unless_baseline_is_green(
            gremlin_session, _baseline_with_failures(tests_failed), exitstatus
        )

        assert (skipped, gremlin_session.enabled) == (True, False)
        assert capsys.readouterr().err == f'pytest-gremlins: skipping mutation testing because {expected_reason}\n'

    def it_names_collection_errors_ahead_of_the_exit_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True, collection_errors=3)

        skipped = _skip_mutation_unless_baseline_is_green(
            gremlin_session, _baseline_with_failures(0), pytest.ExitCode.INTERRUPTED
        )

        assert (skipped, gremlin_session.enabled) == (True, False)
        assert '(3 error(s))' in capsys.readouterr().err
