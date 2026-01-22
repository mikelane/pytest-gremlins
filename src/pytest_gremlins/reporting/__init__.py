"""Reporting module for pytest-gremlins mutation testing results.

This module provides data structures and reporters for presenting
mutation testing results in various formats (console, HTML, JSON).
"""

from pytest_gremlins.reporting.console import ConsoleReporter
from pytest_gremlins.reporting.html import HtmlReporter
from pytest_gremlins.reporting.json_reporter import JsonReporter
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


__all__ = [
    'ConsoleReporter',
    'GremlinResult',
    'GremlinResultStatus',
    'HtmlReporter',
    'JsonReporter',
    'MutationScore',
]
