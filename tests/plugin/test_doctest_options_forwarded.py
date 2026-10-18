"""Doctest collection options typed on the command line reach gremlin runs, so doctest node ids resolve (#594)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION


def _session(
    args: tuple[str, ...], addopts: list[str] | None = None, ini: dict[str, object] | None = None
) -> SimpleNamespace:
    values: dict[str, object] = {'addopts': addopts or [], 'doctest_optionflags': [], 'doctest_encoding': 'utf-8'}
    values.update(ini or {})

    def getini(name: str) -> object:
        if name not in values:
            raise ValueError(name)
        return values[name]

    return SimpleNamespace(invocation_params=SimpleNamespace(args=args, dir=Path.cwd()), getini=getini)


def _unknown_ini(name: str) -> object:
    raise ValueError(name)


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
class DescribeDoctestIniValuesInGremlinRunAddopts:
    def it_forwards_the_resolved_optionflags(self) -> None:
        config = _session((), ini={'doctest_optionflags': ['NORMALIZE_WHITESPACE', 'ELLIPSIS']})

        expected = "-o 'doctest_optionflags=NORMALIZE_WHITESPACE ELLIPSIS'"
        assert plugin._addopts_for_gremlin_runs(config) == expected  # type: ignore[arg-type]

    def it_forwards_a_non_default_encoding(self) -> None:
        config = _session((), ini={'doctest_encoding': 'latin-1'})

        assert plugin._addopts_for_gremlin_runs(config) == '-o doctest_encoding=latin-1'  # type: ignore[arg-type]

    def it_skips_settings_the_session_does_not_know(self) -> None:
        config = SimpleNamespace(getini=_unknown_ini)

        assert plugin._doctest_ini_overrides(config) == []  # type: ignore[arg-type]


@pytest.mark.small
class DescribeFidelityVersionAfterDoctestOptionsAreForwarded:
    def it_retires_verdicts_cached_while_doctest_gremlins_errored(self) -> None:
        assert RUNNER_FIDELITY_VERSION == 'rf18'
