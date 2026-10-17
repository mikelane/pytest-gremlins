"""The tox lint env runs the ruff locked in uv.lock, not whatever PyPI serves today.

Pre-commit and CI both run ruff through ``uv run --frozen``; the tox lint env must do the same so a new
ruff release cannot turn ``tox -e lint`` red or green independently of them.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

TOX_INI_PATH = Path(__file__).resolve().parents[2] / 'tox.ini'


def _read_lint_env() -> configparser.SectionProxy:
    tox_config = configparser.ConfigParser()
    tox_config.read(TOX_INI_PATH, encoding='utf-8')
    return tox_config['testenv:lint']


@pytest.mark.medium
class DescribeToxLintEnv:
    def it_does_not_install_ruff_from_an_unpinned_requirement(self) -> None:
        declared_deps = _read_lint_env().get('deps', '')
        assert 'ruff' not in declared_deps

    @pytest.mark.parametrize('ruff_subcommand', ['ruff check', 'ruff format --check'])
    def it_runs_ruff_through_the_frozen_lockfile(self, ruff_subcommand: str) -> None:
        commands = [line.strip() for line in _read_lint_env()['commands'].split('\n') if line.strip()]
        assert any(command.startswith(f'uv run --frozen {ruff_subcommand}') for command in commands)
