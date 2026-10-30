"""Drift check: the xdist design note does not claim a gremlins use of pytest_configure_node (issues #774, #588)."""

from __future__ import annotations

from pathlib import Path

import pytest

DESIGN_DOC = Path(__file__).resolve().parents[2] / 'docs' / 'design' / 'XDIST_INTEGRATION.md'


@pytest.mark.medium
class DescribeXdistDesignNote:
    def it_does_not_claim_plugin_py_injects_gremlins_tmpdir_through_the_hook(self) -> None:
        text = ' '.join(DESIGN_DOC.read_text().split())

        assert '`gremlins_tmpdir` injection in `plugin.py`' not in text

    def it_labels_the_hook_paragraph_as_xdist_behavior_and_design_history(self) -> None:
        text = ' '.join(DESIGN_DOC.read_text().split())

        assert 'xdist behavior, described here as design history' in text
