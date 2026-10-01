"""Unit tests for the baseline-health gate in ``pytest_sessionfinish`` (issue #534)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _skip_mutation_when_baseline_is_broken,
)


@pytest.mark.small
class DescribeSkipMutationWhenBaselineIsBroken:
    def it_proceeds_when_the_baseline_is_healthy(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = GremlinSession(enabled=True)

        skipped = _skip_mutation_when_baseline_is_broken(session, pytest.ExitCode.OK)

        assert (skipped, session.enabled, capsys.readouterr().err) == (False, True, '')

    def it_proceeds_when_tests_merely_fail(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = GremlinSession(enabled=True)

        skipped = _skip_mutation_when_baseline_is_broken(session, pytest.ExitCode.TESTS_FAILED)

        assert (skipped, session.enabled, capsys.readouterr().err) == (False, True, '')

    def it_skips_and_disables_the_session_on_collection_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = GremlinSession(enabled=True, collection_errors=3)

        skipped = _skip_mutation_when_baseline_is_broken(session, pytest.ExitCode.INTERRUPTED)

        assert (skipped, session.enabled) == (True, False)
        assert '(3 error(s))' in capsys.readouterr().err

    def it_skips_when_the_session_was_interrupted(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = GremlinSession(enabled=True)

        skipped = _skip_mutation_when_baseline_is_broken(session, pytest.ExitCode.INTERRUPTED)

        assert (skipped, session.enabled) == (True, False)
        assert 'was interrupted' in capsys.readouterr().err
