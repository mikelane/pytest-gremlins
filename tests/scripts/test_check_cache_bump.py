"""Tests for scripts/check_cache_bump.py -- the release gate on a changed cache marker without a minor bump (#1036)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(SCRIPTS))
try:
    docs_gate = _load('check_release_docs')
finally:
    sys.path.remove(str(SCRIPTS))


def _entry(upgrade_notes: str = '', fix: str = '- **A fix.** (no docs: test)\n') -> str:
    return (
        '# Changelog\n\n## v1.15.0 (2026-11-22)\n\nSummary.\n\n'
        f'### Upgrade notes\n\n{upgrade_notes}\n### Fix\n\n{fix}\n## v1.14.3 (2026-11-16)\n\nOld.\n'
    )


@pytest.mark.small
class DescribeUpgradeNoteBullets:
    def it_returns_each_bullet_under_upgrade_notes_with_its_continuation_lines_joined(self) -> None:
        changelog = _entry(upgrade_notes='- **First.** One\n  and two. (no docs: x)\n- **Second.** (no docs: y)\n')

        assert docs_gate.upgrade_note_bullets(changelog, '1.15.0') == [
            '**First.** One and two. (no docs: x)',
            '**Second.** (no docs: y)',
        ]

    def it_leaves_out_bullets_under_other_sections(self) -> None:
        changelog = _entry(upgrade_notes='', fix='- **Only a fix.** (no docs: x)\n')

        assert docs_gate.upgrade_note_bullets(changelog, '1.15.0') == []

    def it_returns_nothing_for_a_missing_entry(self) -> None:
        assert docs_gate.upgrade_note_bullets(_entry(), '9.9.9') is None
