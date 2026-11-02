"""The pre-scan worker count: ``prescan_workers`` in pyproject.toml and ``--gremlin-prescan-workers`` (#527)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.config import (
    MAX_PRESCAN_WORKERS,
    GremlinConfig,
    load_config,
    merge_configs,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_pyproject(tmp_path: Path, body: str) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest-gremlins]\n{body}\n', encoding='utf-8')


@pytest.mark.medium
class DescribePrescanWorkersFromFile:
    def it_reads_the_underscore_spelling(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, 'prescan_workers = 3')

        assert load_config(tmp_path).prescan_workers == 3

    def it_reads_the_hyphen_spelling(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, 'prescan-workers = 2')

        assert load_config(tmp_path).prescan_workers == 2

    def it_leaves_the_value_unset_when_absent(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, 'cache = true')

        assert load_config(tmp_path).prescan_workers is None

    @pytest.mark.parametrize('raw', ['0', '-1', '"4"', 'true', '1.5', str(MAX_PRESCAN_WORKERS + 1)])
    def it_rejects_values_that_are_not_a_positive_integer_within_the_cap(self, tmp_path: Path, raw: str) -> None:
        _write_pyproject(tmp_path, f'prescan_workers = {raw}')

        with pytest.raises(ValueError, match=r'prescan_workers must be a positive integer'):
            load_config(tmp_path)


@pytest.mark.small
class DescribePrescanWorkersMerge:
    def it_prefers_the_command_line_over_the_file(self) -> None:
        merged = merge_configs(GremlinConfig(prescan_workers=2), cli_prescan_workers=4)

        assert merged.prescan_workers == 4

    def it_falls_back_to_the_file(self) -> None:
        assert merge_configs(GremlinConfig(prescan_workers=2)).prescan_workers == 2

    def it_stays_unset_without_either(self) -> None:
        assert merge_configs(GremlinConfig()).prescan_workers is None
