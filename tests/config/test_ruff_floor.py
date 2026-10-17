"""The declared ruff floor must be a release that can parse this repo's [tool.ruff] config.

ruff 0.8.0 is the oldest release that accepts the config: it introduced the ``TC`` rule prefix that
``ignore = ["TC003"]`` uses. ``ruff@0.7.4 check src tests`` exits 2 with ``Unknown rule selector: TC003``.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version
import pytest

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / 'pyproject.toml'
OLDEST_RUFF_ACCEPTING_CONFIG = Version('0.8.0')


def _ruff_lower_bound() -> Version:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding='utf-8'))
    ruff_requirements = [
        Requirement(entry)
        for entry in pyproject['dependency-groups']['dev']
        if isinstance(entry, str) and Requirement(entry).name == 'ruff'
    ]
    assert len(ruff_requirements) == 1
    lower_bounds = [Version(spec.version) for spec in ruff_requirements[0].specifier if spec.operator == '>=']
    assert len(lower_bounds) == 1
    return lower_bounds[0]


@pytest.mark.medium
class DescribeRuffFloor:
    def it_is_no_older_than_the_oldest_release_that_parses_the_config(self) -> None:
        assert _ruff_lower_bound() >= OLDEST_RUFF_ACCEPTING_CONFIG
