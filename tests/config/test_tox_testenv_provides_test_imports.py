"""The tox testenv installs every third-party distribution the small/medium suite imports.

tests/config/test_precommit_hook_file_selection.py imports ``pre_commit`` (distribution ``pre-commit``,
which brings ``pyyaml`` and ``identify``); tests/reporting/test_stryker_schema.py imports ``jsonschema``.
Both reach the uv dev env via the dev group, but tox's
``[testenv]`` lists its own deps, so a missing one is a collection error that aborts the whole tox run.

The parametrized list below must cover the third-party imports of that test file (manual sync).
"""

from __future__ import annotations

import configparser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest

TOX_INI_PATH = Path(__file__).resolve().parents[2] / 'tox.ini'


def _declared_requirements(deps_block: str) -> dict[str, Requirement]:
    """Parse a tox ``deps`` block, skipping blanks, whole-line comments and tox options such as ``-r``."""
    requirements: dict[str, Requirement] = {}
    for raw_line in deps_block.split('\n'):
        line = raw_line.split(' #')[0].strip()
        if not line or line.startswith(('#', '-')):
            continue
        requirement = Requirement(line.split(':')[-1].strip())
        requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def _tox_testenv_requirements() -> dict[str, Requirement]:
    tox_config = configparser.ConfigParser()
    tox_config.read(TOX_INI_PATH, encoding='utf-8')
    return _declared_requirements(tox_config['testenv']['deps'])


@pytest.mark.small
class DescribeToxDepsParser:
    def it_skips_tox_only_lines_and_inline_comments(self) -> None:
        deps_block = '\n-r requirements.txt\n# comment\n\npre-commit>=4.6.2  # hooks test\n'

        assert set(_declared_requirements(deps_block)) == {'pre-commit'}


@pytest.mark.medium
class DescribeToxTestenv:
    def it_caps_pre_commit_below_the_next_major_version(self) -> None:
        specifier = _tox_testenv_requirements()['pre-commit'].specifier

        assert '4.6.2' in specifier
        assert '5.0' not in specifier

    @pytest.mark.parametrize('distribution', ['pre-commit', 'jsonschema'])
    def it_installs_distributions_imported_by_the_suite(self, distribution: str) -> None:
        declared_requirements = _tox_testenv_requirements()
        assert canonicalize_name(distribution) in declared_requirements, (
            f'[testenv] deps in tox.ini does not install {distribution!r}'
        )
