"""Tests for the shared node-id marker stripping rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.coverage.nodeid_markers import strip_marker_suffix
from pytest_gremlins.coverage.subprocess_bootstrap import _strip_nodeid_markers
from pytest_gremlins.plugin import (
    _drop_bracketed_suffix,
    _make_node_ids_relative,
)

_CASES = [
    ('test_x[A] [SMALL]', 'test_x[A]'),
    ('test_x[x [y]]', 'test_x[x [y]]'),
    ('test_x[x [y]] [MEDIUM]', 'test_x[x [y]]'),
    ('test_x[GET]', 'test_x[GET]'),
    ('test_x', 'test_x'),
]


@pytest.mark.small
class DescribeStripMarkerSuffix:
    @pytest.mark.parametrize(('nodeid', 'expected'), _CASES)
    def it_strips_only_a_trailing_uppercase_marker(self, nodeid: str, expected: str) -> None:
        assert strip_marker_suffix(nodeid) == expected

    @pytest.mark.parametrize(('nodeid', 'expected'), _CASES)
    def it_agrees_with_the_coverage_subprocess_bootstrap(self, nodeid: str, expected: str) -> None:
        assert _strip_nodeid_markers(nodeid) == expected

    @pytest.mark.parametrize(('nodeid', 'expected'), _CASES)
    def it_agrees_with_the_selection_explainer(self, nodeid: str, expected: str) -> None:
        assert _drop_bracketed_suffix(nodeid) == expected

    @pytest.mark.parametrize(('nodeid', 'expected'), _CASES)
    def it_agrees_with_the_session_node_id_normalizer(self, nodeid: str, expected: str) -> None:
        assert _make_node_ids_relative([nodeid], Path('/nonexistent-rootdir')) == [expected]
