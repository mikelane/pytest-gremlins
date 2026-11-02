"""Adversarial QA for #956: the social cards Read the Docs builds must be reachable."""

from __future__ import annotations

from pathlib import Path
import re

from mkdocs.commands.build import build
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


_ROOT_RELATIVE_LINK = re.compile(r'(?:href|src)="(/[^"#?]*)')


@pytest.mark.large
class DescribeLocalBuildLinkCheck:
    """The site the Documentation workflow builds and hands to lychee --root-dir site --offline."""

    def it_resolves_every_root_relative_link_in_the_404_page_inside_the_built_site(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv('READTHEDOCS', raising=False)
        monkeypatch.delenv('READTHEDOCS_CANONICAL_URL', raising=False)
        site_dir = tmp_path / 'site'
        build(load_config(str(REPO_ROOT / 'mkdocs.yml'), site_dir=str(site_dir)))

        links = _ROOT_RELATIVE_LINK.findall((site_dir / '404.html').read_text(encoding='utf-8'))
        unresolved = [link for link in links if not (site_dir / link.lstrip('/')).exists()]

        assert not unresolved, f'lychee --root-dir site cannot resolve these 404.html links: {unresolved[:5]}'
