"""Tests for PARDONED status in GremlinResultStatus and GremlinResult."""

from __future__ import annotations

import pytest

from pytest_gremlins.reporting.results import GremlinResultStatus


@pytest.mark.small
class DescribeGremlinResultStatusPardoned:
    """Tests for the PARDONED enum value."""

    def it_has_pardoned_status(self):
        assert GremlinResultStatus.PARDONED.value == 'pardoned'

    def it_pardoned_is_distinct_from_survived(self):
        assert GremlinResultStatus.PARDONED != GremlinResultStatus.SURVIVED

    def it_pardoned_is_distinct_from_zapped(self):
        assert GremlinResultStatus.PARDONED != GremlinResultStatus.ZAPPED


@pytest.mark.small
class DescribeGremlinResultWithPardonedStatus:
    """Tests for GremlinResult using PARDONED status."""

    def it_is_not_zapped_when_pardoned(self, make_result):
        result = make_result(GremlinResultStatus.PARDONED)
        assert result.is_zapped is False

    def it_is_not_survived_when_pardoned(self, make_result):
        result = make_result(GremlinResultStatus.PARDONED)
        assert result.is_survived is False
