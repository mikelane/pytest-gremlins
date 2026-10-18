"""Tests for scripts/check_release_docs.py -- the gate that blocks a release with undocumented changes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_release_docs.py'
DOCS_URL = 'https://pytest-gremlins.readthedocs.io/en/latest'


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_release_docs', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['check_release_docs'] = module
    spec.loader.exec_module(module)
    return module


def _entry(gated_bullets: str, section: str = 'Fix') -> str:
    return f"""\
# Changelog

## v2.0.0 (2026-11-01)

Intro paragraph.

### {section}

{gated_bullets}

### Internal

- Bumped a dev dependency. (#1)

## v1.9.0 (2026-10-01)

### Fix

- An old bullet with no docs reference at all. (#2)
"""


@pytest.mark.small
class DescribeEntryLookup:
    def it_reports_a_missing_entry(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems('# Changelog\n\n## v1.0.0 (2026-01-01)\n', 'v2.0.0')

        assert len(problems) == 1
        assert 'v2.0.0' in problems[0]

    @pytest.mark.parametrize('version', ['2.0.0', 'v2.0.0'])
    def it_accepts_the_version_with_or_without_the_v_prefix(self, version: str) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (#3)'

        assert checker.find_problems(_entry(bullet), version) == []

    def it_does_not_match_a_longer_version_with_the_same_prefix(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems('## v2.0.01 (2026-01-01)\n\n### Fix\n\n- x\n', '2.0.0')

        assert len(problems) == 1

    def it_only_checks_the_requested_entry(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (#3)'

        assert checker.find_problems(_entry(bullet), '2.0.0') == []


@pytest.mark.small
class DescribeGatedBullets:
    @pytest.mark.parametrize('section', ['Upgrade notes', 'Feature', 'Fix'])
    def it_fails_a_bullet_with_no_reference_in_each_gated_section(self, section: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry('- **Changed a thing.** (#3)', section), '2.0.0')

        assert len(problems) == 1
        assert 'Changed a thing' in problems[0]
        assert section in problems[0]

    def it_names_the_bullet_by_line_number(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry('- **Changed a thing.** (#3)'), '2.0.0')

        assert 'line 9' in problems[0]

    def it_exempts_the_internal_section(self) -> None:
        checker = _load_checker()

        assert checker.find_problems(_entry('- **Changed a thing.** [docs](x)', 'Internal'), '2.0.0') == []

    def it_accepts_an_exemption_with_a_reason(self) -> None:
        checker = _load_checker()

        bullet = '- **Restored documented behavior.** (no docs: restores the behavior the docs already describe) (#3)'

        assert checker.find_problems(_entry(bullet), '2.0.0') == []

    @pytest.mark.parametrize('exemption', ['(no docs: )', '(no docs:)', '(no docs:   )'])
    def it_rejects_an_empty_exemption(self, exemption: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'- **Fixed it.** {exemption}'), '2.0.0')

        assert len(problems) == 1
        assert 'empty' in problems[0]

    def it_rejects_an_empty_exemption_even_beside_a_reference(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (no docs: )'

        problems = checker.find_problems(_entry(bullet), '2.0.0')

        assert len(problems) == 1

    def it_reads_a_reference_on_a_continuation_line(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** A long\n  description that wraps. [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0') == []

    def it_treats_a_non_docs_link_as_no_reference(self) -> None:
        checker = _load_checker()
        bullet = '- **Fixed it.** [issue](https://github.com/mikelane/pytest-gremlins/issues/3)'

        assert len(checker.find_problems(_entry(bullet), '2.0.0')) == 1

    def it_treats_a_non_latest_docs_url_as_no_reference(self) -> None:
        checker = _load_checker()
        bullet = '- **Fixed it.** [docs](https://pytest-gremlins.readthedocs.io/en/stable/guide/configuration/)'

        assert len(checker.find_problems(_entry(bullet), '2.0.0')) == 1

    def it_reports_every_failing_bullet(self) -> None:
        checker = _load_checker()
        bullets = '- **First.** (#3)\n- **Second.** (#4)'

        assert len(checker.find_problems(_entry(bullets), '2.0.0')) == 2
