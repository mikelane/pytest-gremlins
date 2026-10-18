"""Doctest collection options typed on the command line reach gremlin runs, so doctest node ids resolve (#594)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION


def _session(args: tuple[str, ...], addopts: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_params=SimpleNamespace(args=args, dir=Path.cwd()),
        getini=lambda _name: addopts or [],
    )


@pytest.mark.small
class DescribeDoctestOptionsInGremlinRunAddopts:
    def it_forwards_doctest_modules_from_the_command_line(self) -> None:
        config = _session(('--gremlins', '--doctest-modules'))

        assert plugin._addopts_for_gremlin_runs(config) == '--doctest-modules'  # type: ignore[arg-type]

    def it_forwards_an_inline_doctest_glob(self) -> None:
        config = _session(('--doctest-glob=*.rst',))

        assert plugin._addopts_for_gremlin_runs(config) == "'--doctest-glob=*.rst'"  # type: ignore[arg-type]

    def it_forwards_a_doctest_glob_given_as_a_separate_token(self) -> None:
        config = _session(('--doctest-glob', '*.rst'))

        assert plugin._addopts_for_gremlin_runs(config) == "--doctest-glob '*.rst'"  # type: ignore[arg-type]

    def it_keeps_project_addopts_ahead_of_the_forwarded_options(self) -> None:
        config = _session(('--doctest-modules',), addopts=['--import-mode=importlib'])

        assert plugin._addopts_for_gremlin_runs(config) == '--import-mode=importlib --doctest-modules'  # type: ignore[arg-type]

    def it_adds_nothing_when_no_doctest_option_was_typed(self) -> None:
        config = _session(('--gremlins', '-k', 'doctest'), addopts=['-q'])

        assert plugin._addopts_for_gremlin_runs(config) == '-q'  # type: ignore[arg-type]

    def it_does_not_treat_a_test_path_as_a_doctest_option(self) -> None:
        config = _session(('tests/--doctest-modules-notes.py',))

        assert plugin._addopts_for_gremlin_runs(config) == ''  # type: ignore[arg-type]

    def it_strips_pytest_cov_options_from_project_addopts_as_before(self) -> None:
        config = _session(('--doctest-modules',), addopts=['--cov=src', '-q'])

        assert plugin._addopts_for_gremlin_runs(config) == '-q --doctest-modules'  # type: ignore[arg-type]


@pytest.mark.small
class DescribeFidelityVersionAfterDoctestOptionsAreForwarded:
    def it_retires_verdicts_cached_while_doctest_gremlins_errored(self) -> None:
        assert RUNNER_FIDELITY_VERSION == 'rf18'
