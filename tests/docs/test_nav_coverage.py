"""Drift check 1e: a docs page left out of the nav fails ``mkdocs build --strict``.

mkdocs does the page-by-page check itself once ``validation.nav.omitted_files`` is ``warn``. These tests keep that
setting from being switched off and keep the list of pages left out on purpose from naming pages that are gone.
"""

from __future__ import annotations

from typing import (
    Any,
    cast,
)

import pytest
import yaml

from .docs_facts import (
    DOCS_ROOT,
    REPO_ROOT,
)


class _MkdocsLoader(yaml.SafeLoader):
    """Reads mkdocs.yml without running the ``!!python/...`` tags that the markdown extensions use."""


_MkdocsLoader.add_multi_constructor('tag:yaml.org,2002:python/', lambda _loader, _suffix, _node: None)


def _mkdocs_config() -> dict[str, Any]:
    config = yaml.load((REPO_ROOT / 'mkdocs.yml').read_text(encoding='utf-8'), Loader=_MkdocsLoader)  # noqa: S506
    return cast('dict[str, Any]', config)


@pytest.mark.medium
class DescribeNavCoverage:
    """mkdocs.yml makes an orphan page a strict-build failure."""

    def it_warns_about_pages_that_are_not_in_the_nav(self):
        omitted_files = _mkdocs_config().get('validation', {}).get('nav', {}).get('omitted_files')

        assert omitted_files == 'warn'

    def it_lists_only_pages_that_exist_as_left_out_of_the_nav_on_purpose(self):
        listed = _mkdocs_config().get('not_in_nav', '').split()

        missing = [page for page in listed if not (DOCS_ROOT / page).is_file()]

        assert not missing, f'not_in_nav in mkdocs.yml names pages that do not exist: {missing}'
