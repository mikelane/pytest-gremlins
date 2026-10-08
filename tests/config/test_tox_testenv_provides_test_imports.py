"""The tox testenv installs every third-party module the small/medium suite imports.

tests/config/test_precommit_hook_file_selection.py imports ``yaml`` and ``identify``. They reach the
uv dev env only transitively via pre-commit; tox's ``[testenv]`` lists its own deps, so a missing
module there is a collection error that aborts the whole tox run.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

TOX_INI = Path(__file__).resolve().parents[2] / 'tox.ini'


@pytest.mark.medium
class DescribeToxTestenv:
    @pytest.mark.parametrize('distribution', ['pyyaml', 'identify'])
    def it_installs_distributions_imported_by_the_suite(self, distribution: str) -> None:
        parser = configparser.ConfigParser()
        parser.read(TOX_INI, encoding='utf-8')
        testenv = parser['testenv']
        provided = testenv.get('deps', '').lower() + ' ' + testenv.get('dependency_groups', '').lower()
        assert distribution in provided or 'dev' in provided.split()
