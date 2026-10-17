"""The declared pytest floor is the oldest pytest CI actually tests, and the latest pytest is tested too.

pyproject.toml, tox.ini and the ``pytest-compat`` CI job must agree, otherwise the floor we claim is a
version nobody ran the suite against.
"""

from __future__ import annotations

import configparser
from pathlib import Path
import tomllib
from typing import Any

from packaging.requirements import Requirement
from packaging.version import Version
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LATEST = 'latest'


def _pytest_floor(requirement_lines: list[str]) -> Version:
    for line in requirement_lines:
        requirement = Requirement(line.split(':')[-1].strip())
        if requirement.name == 'pytest':
            (floor,) = [spec for spec in requirement.specifier if spec.operator == '>=']
            return Version(floor.version)
    raise AssertionError('no pytest requirement found')


def _ci_pytest_axis() -> list[str]:
    workflow: dict[str, Any] = yaml.safe_load((REPO_ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    return list(workflow['jobs']['pytest-compat']['strategy']['matrix']['pytest'])


@pytest.mark.medium
class DescribePytestVersionMatrix:
    def it_declares_the_floor_in_pyproject(self) -> None:
        pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))

        assert _pytest_floor(pyproject['project']['dependencies']) == Version(_ci_pytest_axis()[0])

    def it_declares_the_same_floor_in_tox(self) -> None:
        tox_config = configparser.ConfigParser()
        tox_config.read(REPO_ROOT / 'tox.ini', encoding='utf-8')
        tox_lines = [line for line in tox_config['testenv']['deps'].split('\n') if line.strip()]

        assert _pytest_floor(tox_lines) == Version(_ci_pytest_axis()[0])

    def it_tests_the_latest_pytest_last(self) -> None:
        assert _ci_pytest_axis()[-1] == LATEST

    def it_tests_the_oldest_release_of_each_supported_major(self) -> None:
        pinned = [Version(entry) for entry in _ci_pytest_axis() if entry != LATEST]

        assert [version.major for version in pinned] == sorted({version.major for version in pinned})

    def it_requires_every_pinned_version_to_be_at_or_above_the_floor(self) -> None:
        pinned = [Version(entry) for entry in _ci_pytest_axis() if entry != LATEST]

        assert min(pinned) == pinned[0]

    def it_includes_the_compat_job_in_the_aggregate_check(self) -> None:
        workflow = yaml.safe_load((REPO_ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))

        assert 'pytest-compat' in workflow['jobs']['all-checks']['needs']
