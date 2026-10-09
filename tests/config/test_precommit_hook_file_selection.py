"""Commit-stage uv hooks (issue #583) select the files the remote hooks they replaced did.

The remote hooks issue #583 replaced declared ``types_or: [python, pyi]`` (mirrors-mypy, limited to
``src/`` by the local ``files`` filter) and ``types_or: [python, pyi, jupyter]`` (ruff-pre-commit).
Selection is decided by pre-commit's own ``Classifier`` over hooks loaded with ``load_config``, so
the config's ``files``, ``exclude``, ``types``, ``types_or`` and ``exclude_types`` are applied exactly
as ``pre-commit run`` applies them.

Third-party imports here must stay covered by test_tox_testenv_provides_test_imports.py (manual sync).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pre_commit.clientlib import load_config
from pre_commit.commands.run import Classifier
from pre_commit.hook import Hook
from pre_commit.prefix import Prefix
import pytest

PRE_COMMIT_CONFIG_PATH = Path(__file__).resolve().parents[2] / '.pre-commit-config.yaml'

RUFF_HOOK_IDS = ['ruff-check-commit', 'ruff-format-commit']
ALL_COMMIT_HOOK_IDS = [*RUFF_HOOK_IDS, 'mypy-commit']


def _find_hook_by_id(hook_id: str) -> Hook:
    config = load_config(str(PRE_COMMIT_CONFIG_PATH))
    hook_config: dict[str, Any] | None = next(
        (hook for repo in config['repos'] for hook in repo['hooks'] if hook['id'] == hook_id),
        None,
    )
    assert hook_config is not None, f'hook {hook_id!r} missing from .pre-commit-config.yaml'
    return Hook.create('local', Prefix(str(PRE_COMMIT_CONFIG_PATH.parent)), hook_config)


def _selected_filenames(hook_id: str, filename: str, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return what pre-commit passes the hook when ``filename`` is staged (Classifier needs the file on disk)."""
    (workdir / filename).parent.mkdir(parents=True, exist_ok=True)
    (workdir / filename).touch()
    monkeypatch.chdir(workdir)
    return list(Classifier([filename]).filenames_for_hook(_find_hook_by_id(hook_id)))


@pytest.mark.medium
class DescribeCommitStageUvHooks:
    @pytest.mark.parametrize('hook_id', ALL_COMMIT_HOOK_IDS)
    @pytest.mark.parametrize('filename', ['src/pytest_gremlins/_mod.py', 'src/pytest_gremlins/_stub.pyi'])
    def it_selects_python_and_stub_sources(
        self, hook_id: str, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _selected_filenames(hook_id, filename, tmp_path, monkeypatch) == [filename]

    @pytest.mark.parametrize('hook_id', RUFF_HOOK_IDS)
    def it_selects_notebooks_for_ruff(self, hook_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _selected_filenames(hook_id, 'tests/notebook.ipynb', tmp_path, monkeypatch) == ['tests/notebook.ipynb']

    @pytest.mark.parametrize('hook_id', RUFF_HOOK_IDS)
    @pytest.mark.parametrize('filename', ['README.md', 'tox.ini'])
    def it_skips_non_python_files_for_ruff(
        self, hook_id: str, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _selected_filenames(hook_id, filename, tmp_path, monkeypatch) == []

    @pytest.mark.parametrize('filename', ['tests/test_x.py', 'src/pytest_gremlins/notes.md'])
    def it_skips_files_mypy_does_not_check(
        self, filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _selected_filenames('mypy-commit', filename, tmp_path, monkeypatch) == []

    def it_names_the_missing_hook_when_the_id_is_unknown(self) -> None:
        with pytest.raises(AssertionError, match="hook 'no-such-hook' missing"):
            _find_hook_by_id('no-such-hook')
