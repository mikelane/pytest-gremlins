"""A configured session applies the batch size and report formats the named default constants declare."""

from __future__ import annotations

import json
from typing import cast

import pytest

from pytest_gremlins.plugin import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_REPORT_FORMATS,
    GremlinSession,
)

APPLIED_FILE = 'applied.json'
RECORD_APPLIED_SETTINGS = f"""
import json
import pytest
from pytest_gremlins import plugin


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    session = plugin._get_session()
    with open({APPLIED_FILE!r}, 'w', encoding='utf-8') as handle:
        json.dump({{'batch_size': session.batch_size, 'report_formats': session.report_formats}}, handle)
"""


@pytest.fixture
def applied_settings(pytester: pytest.Pytester) -> dict[str, object]:
    """Configure a gremlins session in a project with no settings and return what it applied."""
    pytester.makeconftest(RECORD_APPLIED_SETTINGS)
    pytester.makepyfile(test_sample='def test_sample():\n    pass\n')
    pytester.runpytest_inprocess('--gremlins')
    return cast('dict[str, object]', json.loads((pytester.path / APPLIED_FILE).read_text(encoding='utf-8')))


@pytest.mark.medium
class DescribeAppliedDefaults:
    """The defaults a configured session applies are the named constants."""

    def it_applies_the_batch_size_constant_when_configuring_a_session(self, applied_settings):
        assert applied_settings['batch_size'] == DEFAULT_BATCH_SIZE

    def it_applies_the_report_formats_constant_when_configuring_a_session(self, applied_settings):
        assert applied_settings['report_formats'] == list(DEFAULT_REPORT_FORMATS)

    def it_gives_a_bare_session_the_batch_size_constant(self):
        assert GremlinSession().batch_size == DEFAULT_BATCH_SIZE

    def it_gives_a_bare_session_the_report_formats_constant(self):
        assert GremlinSession().report_formats == list(DEFAULT_REPORT_FORMATS)
