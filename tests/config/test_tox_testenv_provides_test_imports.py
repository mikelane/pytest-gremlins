"""The tox testenv installs every third-party distribution the small/medium suite imports.

tests/config/test_precommit_hook_file_selection.py imports ``pre_commit`` (distribution ``pre-commit``,
which brings ``pyyaml`` and ``identify``). It reaches the uv dev env via the dev group, but tox's
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


@pytest.mark.medium
class DescribeToxTestenv:
    @pytest.mark.parametrize('distribution', ['pre-commit'])
    def it_installs_distributions_imported_by_the_suite(self, distribution: str) -> None:
        tox_config = configparser.ConfigParser()
        tox_config.read(TOX_INI_PATH, encoding='utf-8')
        declared_requirements = {
            canonicalize_name(Requirement(line).name)
            for line in tox_config['testenv']['deps'].split('\n')
            if line.strip()
        }
        assert canonicalize_name(distribution) in declared_requirements, (
            f'[testenv] deps in tox.ini does not install {distribution!r}'
        )
