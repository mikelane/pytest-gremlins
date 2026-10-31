"""The load_config split keeps the key check order of the single-function version (issue #796).

The single-function version validated keys in this order: workers, batch_size, coverage_timeout,
mutant_timeout, cache, report, max_pardons_pct, max_pardons, operators, paths, exclude. A pyproject with two
invalid keys must keep reporting the earlier one in that order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, body: str) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest-gremlins]\n{body}\n', encoding='utf-8')


@pytest.mark.medium
@pytest.mark.parametrize(
    ('body', 'expected_error'),
    [
        ('workers = 0\noperators = "x"', r'^Invalid workers value 0\.'),
        ('workers = 0\npaths = "x"', r'^Invalid workers value 0\.'),
        ('batch_size = 0\ncache = 1', r'^\[tool\.pytest-gremlins\]\.batch_size must be a positive integer'),
        ('batch_size = 0\nreport = "bogus"', r'^\[tool\.pytest-gremlins\]\.batch_size must be a positive integer'),
        ('cache = 1\ncoverage_timeout = 0', r'^\[tool\.pytest-gremlins\]\.coverage_timeout must be'),
        ('max_pardons = -1\nmutant_timeout = 0', r'^\[tool\.pytest-gremlins\]\.mutant_timeout must be'),
        ('report = "bogus"\noperators = "x"', r'^Unknown report format'),
    ],
)
def it_reports_the_same_invalid_key_as_main_when_two_keys_are_invalid(
    tmp_path: Path, body: str, expected_error: str
) -> None:
    _write(tmp_path, body)

    with pytest.raises(ValueError, match=expected_error):
        load_config(tmp_path, on_warning=lambda _m: None)


@pytest.mark.medium
def it_does_not_warn_about_empty_operators_when_an_earlier_key_is_invalid(tmp_path: Path) -> None:
    _write(tmp_path, 'operators = []\nworkers = 0')
    warned: list[str] = []

    with pytest.raises(ValueError, match='Invalid workers value'):
        load_config(tmp_path, on_warning=warned.append)

    assert warned == []


@pytest.mark.medium
def it_stays_silent_about_empty_operators_when_told_the_cli_overrides_them(tmp_path: Path) -> None:
    _write(tmp_path, 'operators = []')
    warned: list[str] = []

    load_config(tmp_path, on_warning=warned.append, warn_when_operators_empty=False)

    assert warned == []
