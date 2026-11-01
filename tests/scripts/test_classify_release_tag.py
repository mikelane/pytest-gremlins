"""Tests for scripts/classify_release_tag.py and its wiring in release.yml (issue #635)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'classify_release_tag.py'
RELEASE_WORKFLOW = ROOT / '.github' / 'workflows' / 'release.yml'

PRERELEASE_TAGS = ['v1.9.0a1', 'v1.8.0b8', 'v1.9.0b3', 'v1.9.0rc1', 'v2.0.0rc12']
FINAL_TAGS = ['v1.12.0', 'v1.12.2', 'v0.1.0', 'v10.20.30']
EXTENDED_PRERELEASE_TAGS = [
    'v1.9.0.dev1',
    'v1.9.0b1.dev2',
    'v1.9.0rc1.post1',
    'v1.9.0c1',
    'v1.9.0alpha1',
    'v1.9.0b',
    'v1.9.0.post1.dev1',
]
VERIFY_ACCEPTED_NON_PRERELEASE_TAGS = ['v1.9.0src', 'v1.9.0post1', 'v1.9.0.post1', 'v1.9.0.']
NON_PEP440_TAGS = ['v1.9.0-beta.1', 'v1.9.0src', 'v1.9.0post1', 'v1.9.0.post1', 'v1.9.0.']


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location('classify_release_tag', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    return list(workflow['jobs']['github-release']['steps'])


@pytest.mark.small
class DescribeIsPrerelease:
    @pytest.mark.parametrize('tag', PRERELEASE_TAGS)
    def it_marks_pep440_pre_release_tags_as_prerelease(self, tag: str) -> None:
        assert _load().is_prerelease(tag) is True

    @pytest.mark.parametrize('tag', EXTENDED_PRERELEASE_TAGS)
    def it_marks_every_verify_accepted_pep440_pre_release_as_prerelease(self, tag: str) -> None:
        assert _load().is_prerelease(tag) is True

    @pytest.mark.parametrize(
        'tag', PRERELEASE_TAGS + EXTENDED_PRERELEASE_TAGS + FINAL_TAGS + VERIFY_ACCEPTED_NON_PRERELEASE_TAGS
    )
    def it_agrees_with_packaging_on_every_tag(self, tag: str) -> None:
        packaging_version = pytest.importorskip('packaging.version')

        try:
            expected = packaging_version.Version(tag).is_prerelease
        except packaging_version.InvalidVersion:
            expected = False

        assert _load().is_prerelease(tag) is expected

    @pytest.mark.parametrize('tag', FINAL_TAGS)
    def it_marks_final_tags_as_not_prerelease(self, tag: str) -> None:
        assert _load().is_prerelease(tag) is False

    @pytest.mark.parametrize('tag', NON_PEP440_TAGS)
    def it_does_not_mark_tags_without_a_pep440_pre_release_segment(self, tag: str) -> None:
        assert _load().is_prerelease(tag) is False


@pytest.mark.medium
class DescribeClassifyReleaseTagCli:
    def it_writes_the_decision_to_github_output(self, tmp_path: Path) -> None:
        output = tmp_path / 'github_output'

        result = subprocess.run(
            [sys.executable, str(SCRIPT), 'v1.9.0b3'],
            env={'GITHUB_OUTPUT': str(output), 'PATH': '/usr/bin:/bin'},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert output.read_text() == 'prerelease=true\n'

    def it_prints_the_decision_when_not_running_in_actions(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), 'v1.12.0'],
            env={'PATH': '/usr/bin:/bin'},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.stdout.strip() == 'prerelease=false'


@pytest.mark.medium
class DescribeReleaseWorkflowPrereleaseFlag:
    def it_derives_the_prerelease_flag_from_a_classify_step_output(self) -> None:
        steps = _release_steps()
        classify = next(step for step in steps if 'classify_release_tag.py' in str(step.get('run', '')))
        create = next(step for step in steps if str(step.get('uses', '')).startswith('softprops/action-gh-release'))

        assert steps.index(classify) < steps.index(create)
        assert create['with']['prerelease'] == f'${{{{ steps.{classify["id"]}.outputs.prerelease }}}}'
