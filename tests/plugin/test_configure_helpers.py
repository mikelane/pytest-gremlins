"""Unit tests for the helpers extracted from ``pytest_configure``.

These run in-process with no filesystem or subprocess access so coverage tools
measure them directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import (
    Path,
    PurePosixPath,
)
from types import SimpleNamespace
from typing import cast

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.config import GremlinConfig


@dataclass
class _FakeOption:
    gremlin_max_pardons_pct: float | None = None
    max_pardons: int | None = None


@dataclass
class _FakeConfig:
    option: _FakeOption


def _config(**option_values: float | None) -> pytest.Config:
    return cast('pytest.Config', _FakeConfig(option=_FakeOption(**option_values)))  # type: ignore[arg-type]


@pytest.mark.small
class DescribeReadValidatedPardonLimits:
    @pytest.mark.parametrize(
        ('option_values', 'expected'),
        [
            ({}, (None, None)),
            ({'gremlin_max_pardons_pct': 0}, (0, None)),
            ({'gremlin_max_pardons_pct': 100}, (100, None)),
            ({'gremlin_max_pardons_pct': 12.5}, (12.5, None)),
            ({'max_pardons': 0}, (None, 0)),
            ({'max_pardons': 7}, (None, 7)),
            ({'gremlin_max_pardons_pct': 50, 'max_pardons': 3}, (50, 3)),
        ],
    )
    def it_returns_the_cli_limits_when_valid_or_absent(
        self, option_values: dict[str, float], expected: tuple[float | None, int | None]
    ) -> None:
        assert plugin._read_validated_pardon_limits(_config(**option_values)) == expected

    @pytest.mark.parametrize('pct', [100.01, 150, -0.1, -5])
    def it_exits_with_a_usage_error_for_an_out_of_range_pct(self, pct: float) -> None:
        with pytest.raises(pytest.exit.Exception, match='--gremlin-max-pardons-pct must be between 0 and 100') as exc:
            plugin._read_validated_pardon_limits(_config(gremlin_max_pardons_pct=pct))
        assert exc.value.returncode == pytest.ExitCode.USAGE_ERROR

    @pytest.mark.parametrize('max_pardons', [-1, -10])
    def it_exits_with_a_usage_error_for_a_negative_max_pardons(self, max_pardons: int) -> None:
        with pytest.raises(pytest.exit.Exception, match='--max-pardons must be >= 0') as exc:
            plugin._read_validated_pardon_limits(_config(max_pardons=max_pardons))
        assert exc.value.returncode == pytest.ExitCode.USAGE_ERROR


_ROOT = Path('/project')


@pytest.fixture
def existing_paths(monkeypatch: pytest.MonkeyPatch) -> set[PurePosixPath]:
    existing: set[PurePosixPath] = set()
    monkeypatch.setattr(Path, 'exists', lambda self: PurePosixPath(self) in existing)
    return existing


@pytest.fixture
def no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ('discover_source_paths', 'discover_by_project_name', 'discover_by_setup_cfg'):
        monkeypatch.setattr(plugin, name, lambda _root: None)
    monkeypatch.setattr(plugin, 'discover_by_importlib_metadata', lambda _root: None)


def _config_with_paths(paths: list[str]) -> GremlinConfig:
    return GremlinConfig(paths=paths)


@pytest.mark.small
class DescribeResolveTargetPaths:
    def it_returns_configured_relative_paths_that_exist(self, existing_paths: set[PurePosixPath]) -> None:
        existing_paths.add(PurePosixPath('/project/pkg'))
        resolved = plugin._resolve_target_paths(_ROOT, _config_with_paths(['pkg']))
        assert resolved == [Path('/project/pkg')]

    def it_keeps_absolute_configured_paths_as_given(self, existing_paths: set[PurePosixPath]) -> None:
        existing_paths.add(PurePosixPath('/elsewhere/lib'))
        resolved = plugin._resolve_target_paths(_ROOT, _config_with_paths(['/elsewhere/lib']))
        assert resolved == [Path('/elsewhere/lib')]

    def it_drops_configured_paths_that_do_not_exist(self, existing_paths: set[PurePosixPath]) -> None:
        existing_paths.add(PurePosixPath('/project/real'))
        resolved = plugin._resolve_target_paths(_ROOT, _config_with_paths(['missing', 'real']))
        assert resolved == [Path('/project/real')]

    @pytest.mark.usefixtures('existing_paths')
    def it_returns_an_empty_list_when_every_configured_path_is_missing(self) -> None:
        assert plugin._resolve_target_paths(_ROOT, _config_with_paths(['gone', 'also_gone'])) == []

    def it_uses_discovered_paths_relative_to_the_rootdir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(plugin, 'discover_source_paths', lambda _root: [Path('src/found')])
        assert plugin._resolve_target_paths(_ROOT, GremlinConfig()) == [Path('/project/src/found')]

    @pytest.mark.usefixtures('no_discovery')
    def it_defaults_to_src_when_nothing_is_discovered(self, existing_paths: set[PurePosixPath]) -> None:
        existing_paths.add(PurePosixPath('/project/src'))
        assert plugin._resolve_target_paths(_ROOT, GremlinConfig()) == [Path('/project/src')]

    @pytest.mark.usefixtures('existing_paths', 'no_discovery')
    def it_warns_and_falls_back_to_the_rootdir_without_src(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=plugin.logger.name):
            resolved = plugin._resolve_target_paths(_ROOT, GremlinConfig())
        assert resolved == [_ROOT]
        assert 'No source paths discovered' in caplog.text


def _collect_only_config(*, collectonly: bool, worker: bool = False) -> pytest.Config:
    option = _FakeOption()
    option.collectonly = collectonly  # type: ignore[attr-defined]
    fake = SimpleNamespace(option=option, workerinput={}) if worker else SimpleNamespace(option=option)
    return cast('pytest.Config', fake)


@pytest.fixture
def isolated_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin, '_gremlin_session', None)


@pytest.mark.small
@pytest.mark.usefixtures('isolated_session')
class DescribeMaybeShortCircuitForInactiveRun:
    def it_leaves_the_session_alone_without_collect_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert plugin._maybe_short_circuit_for_inactive_run(_collect_only_config(collectonly=False)) is False
        assert plugin._get_session() is None
        assert capsys.readouterr().err == ''

    def it_disables_the_session_and_prints_one_stderr_notice_under_collect_only(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert plugin._maybe_short_circuit_for_inactive_run(_collect_only_config(collectonly=True)) is True
        session = plugin._get_session()
        assert session is not None
        assert session.enabled is False
        captured = capsys.readouterr()
        assert captured.err == 'pytest-gremlins: --collect-only detected, skipping mutation testing\n'
        assert captured.out == ''

    def it_stays_silent_on_xdist_workers(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert plugin._maybe_short_circuit_for_inactive_run(_collect_only_config(collectonly=True, worker=True)) is True
        assert capsys.readouterr().err == ''


@pytest.mark.medium
@pytest.mark.usefixtures('isolated_session')
class DescribeConfigureUnderCollectOnly:
    def it_disables_the_session_without_creating_the_cache(
        self, tmp_path: Path, make_pytest_config: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\ncache = true\n')
        config = make_pytest_config(tmp_path)  # type: ignore[operator]
        config.option.collectonly = True

        plugin.pytest_configure(config)

        session = plugin._get_session()
        assert session is not None
        assert session.enabled is False
        assert not (tmp_path / '.gremlins_cache').exists()
        assert 'skipping mutation testing' in capsys.readouterr().err
