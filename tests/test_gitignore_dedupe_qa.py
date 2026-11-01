"""Adversarial QA (#606): the .gitignore dedupe must ignore every path origin/main ignored."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.medium
class DescribeGitignoreDedupe:
    """Every path the pre-dedupe .gitignore ignored stays ignored."""

    @pytest.mark.parametrize('path', ['site/index.html', 'docs/site/index.html', 'tools/site/index.html'])
    def it_ignores_a_mkdocs_site_directory_at_any_depth(self, path: str) -> None:
        result = subprocess.run(
            ['git', 'check-ignore', '--no-index', '-q', path],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
        )

        assert result.returncode == 0
