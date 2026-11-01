"""The base tox env keeps its marker and coverage flags when a path is passed after ``--`` (issue #849 follow-up)."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

TOX_INI_PATH = Path(__file__).resolve().parents[2] / 'tox.ini'


def _base_commands() -> str:
    tox_config = configparser.ConfigParser()
    tox_config.read(TOX_INI_PATH, encoding='utf-8')
    return tox_config['testenv']['commands']


@pytest.mark.medium
class DescribeToxBaseEnvPosargs:
    def it_puts_only_the_test_path_inside_the_posargs_default(self) -> None:
        assert '{posargs:tests}' in _base_commands()

    def it_keeps_the_marker_expression_outside_the_posargs_default(self) -> None:
        assert 'pytest -m "small or medium"' in _base_commands()

    def it_keeps_the_coverage_flags_outside_the_posargs_default(self) -> None:
        assert '--cov=pytest_gremlins --cov-report=term-missing {posargs:tests}' in _base_commands()
