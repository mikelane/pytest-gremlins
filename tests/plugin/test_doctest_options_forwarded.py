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
    values: dict[str, object] = {'addopts': addopts or []}
    values.update(ini or {})

    def getini(name: str) -> object:
        if name not in values:
            raise ValueError(name)
        return values[name]

    return SimpleNamespace(
        invocation_params=SimpleNamespace(args=args, dir=Path.cwd()),
        getini=getini,
        pluginmanager=SimpleNamespace(hasplugin=lambda _name: False),
    )


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
class DescribeDoctestIniValuesAsTopLevelGremlinRunArguments:
    def it_leaves_the_resolved_optionflags_out_of_the_addopts_value(self) -> None:
        config = _session(('--doctest-modules',), ini={'doctest_optionflags': ['NORMALIZE_WHITESPACE', 'ELLIPSIS']})

        assert plugin._addopts_for_gremlin_runs(config) == '--doctest-modules'  # type: ignore[arg-type]

    def it_leaves_a_non_default_encoding_out_of_the_addopts_value(self) -> None:
        config = _session((), ini={'doctest_encoding': 'latin-1'})

        assert plugin._addopts_for_gremlin_runs(config) == ''  # type: ignore[arg-type]

    def it_returns_the_resolved_optionflags_as_separate_dash_o_arguments(self) -> None:
        config = _session((), ini={'doctest_optionflags': ['NORMALIZE_WHITESPACE', 'ELLIPSIS']})

        assert plugin._doctest_ini_overrides(config) == [  # type: ignore[arg-type]
            '-o',
            'doctest_optionflags=NORMALIZE_WHITESPACE ELLIPSIS',
        ]

    def it_returns_a_non_default_encoding_as_a_dash_o_argument(self) -> None:
        config = _session((), ini={'doctest_encoding': 'latin-1'})

        assert plugin._doctest_ini_overrides(config) == ['-o', 'doctest_encoding=latin-1']  # type: ignore[arg-type]

    def it_returns_an_explicitly_empty_optionflags_value(self) -> None:
        config = _session((), ini={'doctest_optionflags': []})

        assert plugin._doctest_ini_overrides(config) == ['-o', 'doctest_optionflags=']  # type: ignore[arg-type]

    def it_puts_the_overrides_in_the_test_command_outside_the_addopts_value(self) -> None:
        command = plugin._build_test_command(None, '-q', doctest_ini_overrides=['-o', 'doctest_optionflags=ELLIPSIS'])

        assert command[command.index('doctest_optionflags=ELLIPSIS') - 1] == '-o'
        assert 'addopts=-q' in command
        assert not any(token.startswith('addopts=') and 'doctest_' in token for token in command)

    def it_puts_the_overrides_in_the_bootstrapped_test_command_too(self, tmp_path: Path) -> None:
        command = plugin._build_test_command(tmp_path, '', doctest_ini_overrides=['-o', 'doctest_encoding=latin-1'])

        assert command[command.index('doctest_encoding=latin-1') - 1] == '-o'
        assert 'addopts=' in command

    def it_keys_the_cache_on_the_resolved_doctest_settings(self) -> None:
        config = _session((), ini={'doctest_optionflags': ['ELLIPSIS'], 'doctest_encoding': 'utf-8'})
        loose = _session((), ini={'doctest_optionflags': ['NORMALIZE_WHITESPACE'], 'doctest_encoding': 'utf-8'})

        strict_key = plugin._gremlin_run_rerun_cache_settings(config)  # type: ignore[arg-type]
        loose_key = plugin._gremlin_run_rerun_cache_settings(loose)  # type: ignore[arg-type]

        assert strict_key != loose_key

    def it_skips_settings_the_session_does_not_know(self) -> None:
        config = SimpleNamespace(getini=_unknown_ini)

        assert plugin._doctest_ini_overrides(config) == []  # type: ignore[arg-type]


@pytest.mark.medium
class DescribeDoctestIniValuesInThePrescanCommand:
    def it_puts_the_overrides_in_the_coverage_prescan_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[list[str]] = []

        def capture(cmd: list[str], *_args: object) -> None:
            captured.append(cmd)
            raise plugin.CoveragePrescanLaunchError(OSError('stop'))

        monkeypatch.setattr(plugin, '_launch_prescan', capture)

        with pytest.raises(plugin.CoveragePrescanLaunchError):
            plugin._run_tests_with_coverage(
                [], tmp_path, preserved_addopts='-q', doctest_ini_overrides=['-o', 'doctest_encoding=latin-1']
            )

        command = captured[0]
        assert command[command.index('doctest_encoding=latin-1') - 1] == '-o'
        assert 'addopts=-q' in command


@pytest.mark.small
class DescribeFidelityVersionAfterDoctestOptionsAreForwarded:
    def it_retires_verdicts_cached_while_doctest_gremlins_errored(self) -> None:
        assert RUNNER_FIDELITY_VERSION == 'rf21'
