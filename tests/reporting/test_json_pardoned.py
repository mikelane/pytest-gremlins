"""Tests for pardoned field in JSON report output."""

from __future__ import annotations

import json

import pytest

from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeJsonReportPardonedField:
    """Tests that pardoned count appears in JSON summary output."""

    def it_includes_pardoned_in_summary(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        data = json.loads(JsonReporter().to_json(score))
        assert 'pardoned' in data['summary']

    def it_pardoned_count_matches_pardoned_results(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        data = json.loads(JsonReporter().to_json(score))
        assert data['summary']['pardoned'] == 2

    def it_pardoned_is_zero_when_no_pardoned_results(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        data = json.loads(JsonReporter().to_json(score))
        assert data['summary']['pardoned'] == 0
