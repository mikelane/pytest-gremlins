"""Tests for pragma detection wired into transform_source."""

from __future__ import annotations

import logging

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source


@pytest.mark.small
class DescribeTransformSourcePragmaDetection:
    """Tests for pragma-aware gremlin pardoning in transform_source."""

    def it_marks_gremlin_as_pardoned_when_line_has_pragma(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent] floor division is integer\n'
        gremlins, _ = transform_source(source, 'example.py')
        assert len(gremlins) > 0
        assert all(g.pardoned for g in gremlins)

    def it_sets_pardon_reason_from_pragma(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent] floor division is integer\n'
        gremlins, _ = transform_source(source, 'example.py')
        assert all(g.pardon_reason == 'equivalent: floor division is integer' for g in gremlins)

    def it_does_not_pardon_gremlins_on_lines_without_pragma(self):
        source = 'x = a + b\ny = c // 2  # gremlin: pardon[equivalent] integer math\n'
        gremlins, _ = transform_source(source, 'example.py')
        unpardoned = [g for g in gremlins if g.line_number == 1]
        pardoned = [g for g in gremlins if g.line_number == 2]
        assert all(not g.pardoned for g in unpardoned)
        assert all(g.pardoned for g in pardoned)

    def it_logs_warning_for_dead_pragma_with_no_gremlins_on_line(self, caplog):
        source = 'x = 1  # gremlin: pardon[equivalent] no mutation here\n'
        with caplog.at_level(logging.WARNING):
            transform_source(source, 'example.py')
        assert any('dead' in msg.lower() or 'no gremlin' in msg.lower() for msg in caplog.messages)

    def it_pardon_reason_includes_reason_code_and_justification(self):
        source = 'x = a < b  # gremlin: pardon[untestable] cannot observe mutation\n'
        gremlins, _ = transform_source(source, 'example.py')
        assert all(g.pardon_reason == 'untestable: cannot observe mutation' for g in gremlins)
