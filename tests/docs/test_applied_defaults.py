"""The batch size and report formats the session applies come from named constants the drift check can read."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_REPORT_FORMATS,
    GremlinSession,
)

from .docs_facts import REPO_ROOT

PLUGIN_SOURCE = REPO_ROOT / 'src' / 'pytest_gremlins' / 'plugin.py'


def _names_used_in(function_name: str) -> set[str]:
    tree = ast.parse(PLUGIN_SOURCE.read_text(encoding='utf-8'))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function_name)
    return {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}


@pytest.mark.medium
class DescribeAppliedDefaults:
    """The defaults pytest_configure applies are the named constants."""

    def it_applies_the_batch_size_constant_when_configuring_a_session(self):
        assert 'DEFAULT_BATCH_SIZE' in _names_used_in(plugin.pytest_configure.__name__)

    def it_applies_the_report_formats_constant_when_configuring_a_session(self):
        assert 'DEFAULT_REPORT_FORMATS' in _names_used_in(plugin.pytest_configure.__name__)

    def it_gives_a_bare_session_the_batch_size_constant(self):
        assert GremlinSession().batch_size == DEFAULT_BATCH_SIZE

    def it_gives_a_bare_session_the_report_formats_constant(self):
        assert GremlinSession().report_formats == list(DEFAULT_REPORT_FORMATS)
