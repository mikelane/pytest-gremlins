"""Tests for history management utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_gremlins.reporting.history import (
    append_history_entry,
    load_history,
)
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.medium
class DescribeLoadHistory:
    def it_returns_empty_list_when_file_does_not_exist(self, tmp_path: Path):
        assert load_history(tmp_path / 'missing.json') == []


@pytest.mark.medium
class DescribeLoadHistoryFileIO:
    def it_returns_entries_from_valid_file(self, tmp_path: Path):
        history_file = tmp_path / 'history.json'
        history_file.write_text(json.dumps([{'score': 100.0}]), encoding='utf-8')
        assert load_history(history_file) == [{'score': 100.0}]

    def it_returns_empty_list_when_file_is_corrupt(self, tmp_path: Path):
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not valid json', encoding='utf-8')
        assert load_history(corrupt) == []


@pytest.mark.medium
class DescribeAppendHistoryEntryCorruptRecovery:
    def it_starts_fresh_when_existing_file_is_corrupt(self, make_result, tmp_path: Path):
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not valid json', encoding='utf-8')
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        append_history_entry(rootdir=tmp_path, score=score, history_path=corrupt)
        entries = json.loads(corrupt.read_text(encoding='utf-8'))
        assert len(entries) == 1
        assert entries[0]['score'] == 100.0
