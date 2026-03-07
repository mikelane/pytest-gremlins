"""Tests for extended TOML configuration: workers, cache, report, batch_size fields."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pytest_gremlins import plugin
from pytest_gremlins.config import (
    GremlinConfig,
    discover_source_paths,
    load_config,
    merge_configs,
)


def _make_gremlins_config(
    tmp_path: Path,
    *,
    gremlin_workers: int | None = None,
    gremlin_cache: bool = False,
    gremlin_report: str | None = None,
    gremlin_batch_size: int | None = None,
    gremlin_max_pardons_pct: float | None = None,
) -> object:
    """Build a minimal mock pytest.Config for plugin integration tests."""

    class _MockOption:
        gremlins = True
        gremlin_operators = None
        gremlin_targets = None
        gremlin_clear_cache = False
        gremlin_parallel = False
        gremlin_batch = False
        strict_pardons = False
        gremlin_audit_pardons = False

    option = _MockOption()
    option.gremlin_workers = gremlin_workers  # type: ignore[attr-defined]
    option.gremlin_cache = gremlin_cache  # type: ignore[attr-defined]
    option.gremlin_report = gremlin_report  # type: ignore[attr-defined]
    option.gremlin_batch_size = gremlin_batch_size  # type: ignore[attr-defined]
    option.gremlin_max_pardons_pct = gremlin_max_pardons_pct  # type: ignore[attr-defined]

    pm = MagicMock()
    pm.hasplugin.return_value = False
    pm.get_plugin.return_value = None

    class _MockConfig:
        pass

    mock_config = _MockConfig()
    mock_config.option = option  # type: ignore[attr-defined]
    mock_config.rootdir = tmp_path  # type: ignore[attr-defined]
    mock_config.pluginmanager = pm  # type: ignore[attr-defined]
    return mock_config


@pytest.mark.small
class DescribeGremlinConfigNewFields:
    """GremlinConfig supports workers, cache, report, batch_size fields."""

    def it_defaults_workers_to_none(self):
        config = GremlinConfig()

        assert config.workers is None

    def it_defaults_cache_to_none(self):
        config = GremlinConfig()

        assert config.cache is None

    def it_defaults_report_to_none(self):
        config = GremlinConfig()

        assert config.report is None

    def it_defaults_batch_size_to_none(self):
        config = GremlinConfig()

        assert config.batch_size is None

    def it_accepts_workers_as_int(self):
        config = GremlinConfig(workers=4)

        assert config.workers == 4

    def it_accepts_workers_as_auto_string(self):
        config = GremlinConfig(workers='auto')

        assert config.workers == 'auto'

    def it_accepts_cache_as_bool(self):
        config = GremlinConfig(cache=True)

        assert config.cache is True

    def it_accepts_report_as_string(self):
        config = GremlinConfig(report='html')

        assert config.report == 'html'

    def it_accepts_batch_size_as_int(self):
        config = GremlinConfig(batch_size=50)

        assert config.batch_size == 50


@pytest.mark.small
class DescribeLoadConfigNewFields:
    """load_config reads workers, cache, report, batch_size from pyproject.toml."""

    def it_reads_workers_as_int(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 4\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.workers == 4

    def it_reads_workers_as_auto_string(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = "auto"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.workers == 'auto'

    def it_reads_cache_as_true(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = true\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.cache is True

    def it_reads_cache_as_false(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = false\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.cache is False

    def it_reads_report_as_html(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "html"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == 'html'

    def it_reads_batch_size(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 50\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.batch_size == 50

    def it_defaults_new_fields_to_none_when_absent(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison"]\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.workers is None
        assert loaded_config.cache is None
        assert loaded_config.report is None
        assert loaded_config.batch_size is None

    @pytest.mark.parametrize(
        'workers_value',
        ['notauto', 'zero', ''],
    )
    def it_raises_on_invalid_string_workers(self, tmp_path, workers_value):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(f'[tool.pytest-gremlins]\nworkers = "{workers_value}"\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_zero_workers(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 0\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_negative_workers(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = -1\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_float_workers(self, tmp_path):
        toml = tmp_path / 'pyproject.toml'
        toml.write_text('[tool.pytest-gremlins]\nworkers = 2.5\n')
        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_boolean_workers(self, tmp_path):
        toml = tmp_path / 'pyproject.toml'
        toml.write_text('[tool.pytest-gremlins]\nworkers = true\n')
        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_boolean_batch_size(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = true\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_non_integer_batch_size(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = "large"\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_zero_batch_size(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 0\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_negative_batch_size(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = -5\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_non_boolean_cache(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = 42\n')

        with pytest.raises(ValueError, match='cache'):
            load_config(tmp_path)

    def it_raises_on_string_cache(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = "yes"\n')

        with pytest.raises(ValueError, match='cache'):
            load_config(tmp_path)

    def it_raises_on_non_string_report(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = true\n')

        with pytest.raises(ValueError, match='report'):
            load_config(tmp_path)

    def it_raises_on_integer_report(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = 42\n')

        with pytest.raises(ValueError, match='report'):
            load_config(tmp_path)


@pytest.mark.small
class DescribeLoadConfigValidationLogging:
    """load_config logs a warning before raising ValueError on invalid field types."""

    def it_logs_warning_on_invalid_batch_size_type(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = "large"\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='batch_size'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'batch_size' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_non_positive_batch_size(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = -5\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='batch_size'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'batch_size' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_invalid_cache_type(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = 42\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='cache'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'cache' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_invalid_string_workers(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        toml = tmp_path / 'pyproject.toml'
        toml.write_text('[tool.pytest-gremlins]\nworkers = "banana"\n')
        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='workers'),
        ):
            load_config(tmp_path)
        assert any('workers' in r.message.lower() for r in caplog.records if r.levelno == logging.WARNING)

    def it_logs_warning_on_boolean_workers(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        toml = tmp_path / 'pyproject.toml'
        toml.write_text('[tool.pytest-gremlins]\nworkers = true\n')
        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='workers'),
        ):
            load_config(tmp_path)
        assert any('workers' in r.message.lower() for r in caplog.records if r.levelno == logging.WARNING)

    def it_logs_warning_on_invalid_report_type(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = true\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='report'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'report' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_invalid_max_pardons_pct_type(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = "five"\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='max-pardons-pct'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'max-pardons-pct' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_out_of_range_max_pardons_pct(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 150.0\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='max-pardons-pct'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'max-pardons-pct' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message


@pytest.mark.small
class DescribeMergeConfigsNewFields:
    """merge_configs merges workers, cache, report, batch_size with CLI-beats-TOML precedence."""

    def it_cli_workers_overrides_toml_workers(self):
        file_config = GremlinConfig(workers=2)

        merged_config = merge_configs(file_config, cli_workers=8)

        assert merged_config.workers == 8

    def it_uses_toml_workers_when_cli_workers_is_none(self):
        file_config = GremlinConfig(workers=4)

        merged_config = merge_configs(file_config, cli_workers=None)

        assert merged_config.workers == 4

    def it_resolves_auto_workers_from_toml(self):
        file_config = GremlinConfig(workers='auto')

        merged_config = merge_configs(file_config, cli_workers=None)

        assert merged_config.workers == (os.cpu_count() or 4)

    def it_cli_cache_overrides_toml_cache(self):
        file_config = GremlinConfig(cache=False)

        merged_config = merge_configs(file_config, cli_cache=True)

        assert merged_config.cache is True

    def it_uses_toml_cache_when_cli_cache_is_none(self):
        file_config = GremlinConfig(cache=True)

        merged_config = merge_configs(file_config, cli_cache=None)

        assert merged_config.cache is True

    def it_cli_report_overrides_toml_report(self):
        file_config = GremlinConfig(report='console')

        merged_config = merge_configs(file_config, cli_report='html')

        assert merged_config.report == 'html'

    def it_uses_toml_report_when_cli_report_is_none(self):
        file_config = GremlinConfig(report='html')

        merged_config = merge_configs(file_config, cli_report=None)

        assert merged_config.report == 'html'

    def it_cli_batch_size_overrides_toml_batch_size(self):
        file_config = GremlinConfig(batch_size=20)

        merged_config = merge_configs(file_config, cli_batch_size=100)

        assert merged_config.batch_size == 100

    def it_uses_toml_batch_size_when_cli_batch_size_is_none(self):
        file_config = GremlinConfig(batch_size=50)

        merged_config = merge_configs(file_config, cli_batch_size=None)

        assert merged_config.batch_size == 50

    def it_uses_toml_max_pardons_pct_when_cli_max_pardons_pct_is_none(self):
        file_config = GremlinConfig(max_pardons_pct=10.0)

        merged_config = merge_configs(file_config, cli_max_pardons_pct=None)

        assert merged_config.max_pardons_pct == 10.0

    def it_returns_none_for_new_fields_when_both_are_none(self):
        file_config = GremlinConfig()

        merged_config = merge_configs(file_config)

        assert merged_config.workers is None
        assert merged_config.cache is None
        assert merged_config.report is None
        assert merged_config.batch_size is None
        assert merged_config.max_pardons_pct is None


@pytest.mark.small
class DescribePluginPassesNewFieldsThrough:
    """pytest_configure passes workers, cache, report, batch_size from TOML into the session."""

    def it_toml_workers_flows_into_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 4\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.parallel_workers == 4

    def it_toml_cache_true_flows_into_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = true\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.cache_enabled is True

        # Close the sqlite3 cache connection to avoid ResourceWarning in subsequent tests
        if session.cache is not None:
            session.cache.close()
        plugin._set_session(None)

    def it_toml_report_flows_into_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "json"\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.report_format == 'json'

    def it_toml_batch_size_flows_into_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 25\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.batch_size == 25

    def it_cli_workers_overrides_toml_workers_in_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 2\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path, gremlin_workers=8))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.parallel_workers == 8

    def it_cli_report_overrides_toml_report_in_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "json"\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path, gremlin_report='html'))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.report_format == 'html'

    def it_cli_batch_size_overrides_toml_batch_size_in_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 50\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path, gremlin_batch_size=100))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.batch_size == 100

    def it_cli_max_pardons_pct_overrides_toml_in_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 5.0\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path, gremlin_max_pardons_pct=15.0))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.max_pardons_pct == 15.0


@pytest.mark.small
class DescribeDiscoverSourcePathsLogging:
    """discover_source_paths logs a warning when pyproject.toml contains invalid TOML."""

    def it_logs_warning_on_malformed_toml(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools\npackages = ["broken"')

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'):
            discovered_paths = discover_source_paths(tmp_path)

        assert discovered_paths == []
        assert len(caplog.records) == 1
        assert 'malformed' in caplog.records[0].message.lower() or 'TOML' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message


@pytest.mark.small
class DescribeLoadConfigLogging:
    """load_config logs a warning when pyproject.toml contains invalid TOML."""

    def it_logs_warning_on_malformed_toml(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins\nworkers = 4')

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'):
            loaded_config = load_config(tmp_path)

        assert loaded_config == GremlinConfig()
        assert len(caplog.records) == 1
        assert 'malformed' in caplog.records[0].message.lower() or 'TOML' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message
