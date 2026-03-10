"""Tests for warning-level logging in config loading and source path discovery."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pytest_gremlins.config import (
    GremlinConfig,
    discover_source_paths,
    load_config,
)


@pytest.mark.medium
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
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = "banana"\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='workers'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'workers' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

    def it_logs_warning_on_boolean_workers(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = true\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='workers'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'workers' in caplog.records[0].message
        assert str(tmp_path) in caplog.records[0].message

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


@pytest.mark.medium
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


@pytest.mark.medium
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
