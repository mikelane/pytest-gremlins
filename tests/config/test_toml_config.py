"""Tests for extended TOML configuration: workers, cache, report, batch_size fields."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pytest_gremlins.config import (
    GremlinConfig,
    load_config,
    merge_configs,
)


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

    def it_accepts_report_as_list(self):
        config = GremlinConfig(report=['html'])

        assert config.report == ['html']

    def it_accepts_batch_size_as_int(self):
        config = GremlinConfig(batch_size=50)

        assert config.batch_size == 50


@pytest.mark.medium
class DescribeLoadConfigNewFields:
    """load_config reads workers, cache, report, batch_size from pyproject.toml."""

    def it_reads_workers_as_int(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 4\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.workers == 4

    def it_reads_workers_as_auto_string(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = "auto"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.workers == 'auto'

    def it_reads_cache_as_true(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = true\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.cache is True

    def it_reads_cache_as_false(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = false\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.cache is False

    def it_parses_report_string_as_single_element_list(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "html"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['html']

    def it_parses_comma_separated_report_string(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "json,html"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['json', 'html']

    def it_parses_report_list(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = ["json", "html"]\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['json', 'html']

    def it_strips_whitespace_from_report_formats(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = " json , html "\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['json', 'html']

    def it_raises_on_unknown_report_format(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "xml"\n')

        with pytest.raises(ValueError, match='Unknown report format'):
            load_config(tmp_path)

    def it_reads_batch_size(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 50\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.batch_size == 50

    def it_defaults_new_fields_to_none_when_absent(self, tmp_path: Path) -> None:
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
    def it_raises_on_invalid_string_workers(self, tmp_path: Path, workers_value: str) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(f'[tool.pytest-gremlins]\nworkers = "{workers_value}"\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_zero_workers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 0\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_negative_workers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = -1\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_float_workers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = 2.5\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_boolean_workers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nworkers = true\n')

        with pytest.raises(ValueError, match='workers'):
            load_config(tmp_path)

    def it_raises_on_boolean_batch_size(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = true\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_non_integer_batch_size(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = "large"\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_zero_batch_size(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = 0\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_negative_batch_size(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nbatch_size = -5\n')

        with pytest.raises(ValueError, match='batch_size'):
            load_config(tmp_path)

    def it_raises_on_non_boolean_cache(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = 42\n')

        with pytest.raises(ValueError, match='cache'):
            load_config(tmp_path)

    def it_raises_on_string_cache(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\ncache = "yes"\n')

        with pytest.raises(ValueError, match='cache'):
            load_config(tmp_path)

    def it_raises_on_boolean_report(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = true\n')

        with pytest.raises(ValueError, match='report must be a string or list'):
            load_config(tmp_path)

    def it_raises_on_integer_report(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = 42\n')

        with pytest.raises(ValueError, match='report must be a string or list'):
            load_config(tmp_path)

    def it_raises_on_list_containing_non_strings(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = ["html", 42]\n')

        with pytest.raises(ValueError, match='report must be a string or list of strings'):
            load_config(tmp_path)

    def it_ignores_trailing_comma_in_report_string(self, tmp_path: Path) -> None:
        """Trailing comma in report = "html," does not produce empty-string format."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "html,"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['html']

    def it_ignores_leading_comma_in_report_string(self, tmp_path: Path) -> None:
        """Leading comma in report = ",json" does not produce empty-string format."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = ",json"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['json']

    def it_ignores_double_comma_in_report_string(self, tmp_path: Path) -> None:
        """Double comma in report = "html,,json" does not produce empty-string format."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "html,,json"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['html', 'json']

    def it_deduplicates_report_formats_from_string(self, tmp_path: Path) -> None:
        """Duplicate formats in report = "html,html" are collapsed to one."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = "html,html"\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['html']

    def it_deduplicates_report_formats_from_list(self, tmp_path: Path) -> None:
        """Duplicate formats in report = ["html", "html"] are collapsed to one."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = ["html", "html"]\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.report == ['html']

    def it_raises_on_all_empty_report_string(self, tmp_path: Path) -> None:
        """report = "," (only commas) raises ValueError since no valid format remains."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = ","\n')

        with pytest.raises(ValueError, match='report'):
            load_config(tmp_path)

    def it_raises_on_empty_report_list(self, tmp_path: Path) -> None:
        """report = [] (empty list) raises ValueError since no valid format remains."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nreport = []\n')

        with pytest.raises(ValueError, match='at least one valid format'):
            load_config(tmp_path)


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
        file_config = GremlinConfig(report=['console'])

        merged_config = merge_configs(file_config, cli_report=['html'])

        assert merged_config.report == ['html']

    def it_uses_toml_report_when_cli_report_is_none(self):
        file_config = GremlinConfig(report=['html'])

        merged_config = merge_configs(file_config, cli_report=None)

        assert merged_config.report == ['html']

    def it_cli_multi_report_overrides_toml(self):
        file_config = GremlinConfig(report=['console'])

        merged_config = merge_configs(file_config, cli_report=['json', 'html'])

        assert merged_config.report == ['json', 'html']

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
