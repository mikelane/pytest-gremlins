"""Adversarial QA drift check: no doc still says an unknown --gremlin-operators name is skipped (issue #785)."""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / 'docs'


@pytest.mark.medium
class DescribeUnknownCliOperatorDocs:
    def it_does_not_say_configuration_skips_an_unknown_cli_operator_with_a_warning(self) -> None:
        text = (DOCS_DIR / 'guide' / 'configuration.md').read_text()

        assert 'in `operators` or `--gremlin-operators` is skipped' not in text

    def it_does_not_show_the_ignoring_warning_as_the_configuration_error_symptom(self) -> None:
        text = (DOCS_DIR / 'guide' / 'troubleshooting.md').read_text()
        start = text.index('### Error: Unknown operator requested')
        section = text[start : text.index('**Cause:**', start)]

        assert 'requested, ignoring' not in section
