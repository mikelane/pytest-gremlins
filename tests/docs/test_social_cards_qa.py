"""Adversarial QA for #956: the social cards Read the Docs builds must be reachable."""

from __future__ import annotations

from mkdocs.config import load_config
import pytest

from .docs_facts import REPO_ROOT

RTD_CANONICAL_URL = 'https://pytest-gremlins.readthedocs.io/en/latest/'


@pytest.mark.medium
class DescribeSocialCardsOnReadTheDocs:
    """mkdocs.yml as Read the Docs loads it."""

    def it_points_card_urls_at_the_path_read_the_docs_serves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('READTHEDOCS', 'True')
        monkeypatch.setenv('READTHEDOCS_CANONICAL_URL', RTD_CANONICAL_URL)

        config = load_config(str(REPO_ROOT / 'mkdocs.yml'))

        assert config.site_url == RTD_CANONICAL_URL
