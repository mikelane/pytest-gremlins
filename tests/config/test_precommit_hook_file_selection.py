"""Commit-stage uv hooks (issue #583) select the files the old remote hooks did.

The remote hooks this branch replaced declared ``types_or: [python, pyi]`` (mirrors-mypy) and
``types_or: [python, pyi, jupyter]`` (ruff-pre-commit). These tests apply pre-commit's own
file-selection rules to the local replacements.
"""

from __future__ import annotations

from pathlib import Path
import re

from identify.identify import tags_from_filename
import pytest
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / '.pre-commit-config.yaml'


def _hook(hook_id: str) -> dict[str, object]:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding='utf-8'))
    hooks = [hook for repo in config['repos'] for hook in repo['hooks'] if hook['id'] == hook_id]
    return hooks[0]


def _hook_selects(hook: dict[str, object], filename: str) -> bool:
    tags = tags_from_filename(filename) | {'file'}
    types = frozenset(hook.get('types', ['file']))  # type: ignore[arg-type]
    types_or = frozenset(hook.get('types_or', []))  # type: ignore[arg-type]
    files_match = re.search(str(hook.get('files', '')), filename) is not None
    return files_match and tags >= types and (not types_or or bool(tags & types_or))


@pytest.mark.medium
class DescribeCommitStageUvHooks:
    @pytest.mark.parametrize(
        ('hook_id', 'filename'),
        [
            ('mypy-commit', 'src/pytest_gremlins/_stub.pyi'),
            ('ruff-check-fix', 'tests/notebook.ipynb'),
            ('ruff-format-fix', 'tests/notebook.ipynb'),
        ],
    )
    def it_selects_file_types_the_replaced_remote_hook_selected(self, hook_id: str, filename: str) -> None:
        assert _hook_selects(_hook(hook_id), filename)
