"""Tests for multi-format report dispatch: _write_json_report and format routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _write_json_report,
)
from pytest_gremlins.reporting.score import MutationScore


def _empty_score() -> MutationScore:
    return MutationScore.from_results([])


@pytest.mark.medium
class DescribeWriteJsonReport:
    """_write_json_report writes JSON to coverage/gremlins/gremlins.json."""

    def it_writes_to_coverage_gremlins_gremlins_json(self, tmp_path: Path) -> None:
        score = _empty_score()

        result_path = _write_json_report(score, rootdir=tmp_path)

        assert result_path == tmp_path / 'coverage' / 'gremlins' / 'gremlins.json'
        assert result_path.exists()

    def it_creates_coverage_gremlins_directory_automatically(self, tmp_path: Path) -> None:
        score = _empty_score()
        expected_dir = tmp_path / 'coverage' / 'gremlins'
        assert not expected_dir.exists()

        _write_json_report(score, rootdir=tmp_path)

        assert expected_dir.is_dir()

    def it_writes_valid_json(self, tmp_path: Path) -> None:
        score = _empty_score()

        result_path = _write_json_report(score, rootdir=tmp_path)

        data = json.loads(result_path.read_text())
        assert 'summary' in data
        assert 'results' in data


@pytest.mark.small
class DescribeGremlinSessionReportFormats:
    """GremlinSession.report_formats defaults to ['console']."""

    def it_defaults_report_formats_to_console_list(self) -> None:
        session = GremlinSession()

        assert session.report_formats == ['console']

    def it_accepts_multiple_formats(self) -> None:
        session = GremlinSession(report_formats=['html', 'json'])

        assert session.report_formats == ['html', 'json']
