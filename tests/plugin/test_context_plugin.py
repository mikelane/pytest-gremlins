"""Tests for GremlinContextPlugin - per-test coverage context switching.

GremlinContextPlugin attaches to a coverage.Coverage instance and switches
the active dynamic context before each test phase (setup/run/teardown).
Context format: ``{nodeid}|{when}``  e.g. ``tests/test_foo.py::test_bar|run``
"""

from __future__ import annotations

from types import GeneratorType
from unittest.mock import (
    MagicMock,
    call,
)

import coverage
import pytest

from pytest_gremlins.coverage.context_plugin import GremlinContextPlugin


@pytest.mark.small
class DescribeGremlinContextPluginInit:
    """GremlinContextPlugin stores the coverage instance."""

    def it_stores_coverage_instance(self) -> None:
        """The cov attribute holds the coverage instance passed at construction."""
        cov = MagicMock(spec=coverage.Coverage)
        plugin = GremlinContextPlugin(cov)
        assert plugin.cov is cov

    def it_stores_different_coverage_instance(self) -> None:
        """A different coverage instance is stored correctly - rules out hardcoding."""
        cov_a = MagicMock(spec=coverage.Coverage)
        cov_b = MagicMock(spec=coverage.Coverage)
        plugin_a = GremlinContextPlugin(cov_a)
        plugin_b = GremlinContextPlugin(cov_b)
        assert plugin_a.cov is cov_a
        assert plugin_b.cov is cov_b


@pytest.mark.small
class DescribeGremlinContextPluginSetup:
    """pytest_runtest_setup switches context to ``{nodeid}|setup``."""

    def it_switches_context_to_setup_phase(self) -> None:
        """setup hook switches coverage context to nodeid|setup."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_foo.py::test_bar'

        gen = plugin.pytest_runtest_setup(item=item)
        assert isinstance(gen, GeneratorType)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|setup')

    def it_switches_context_using_item_nodeid(self) -> None:
        """Context uses the actual item nodeid - different nodeid produces different context."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_other.py::test_something_else'

        gen = plugin.pytest_runtest_setup(item=item)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_other.py::test_something_else|setup')


@pytest.mark.small
class DescribeGremlinContextPluginCall:
    """pytest_runtest_call switches context to ``{nodeid}|run``."""

    def it_switches_context_to_run_phase(self) -> None:
        """call hook switches coverage context to nodeid|run."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_foo.py::test_bar'

        gen = plugin.pytest_runtest_call(item=item)
        assert isinstance(gen, GeneratorType)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|run')

    def it_switches_context_using_item_nodeid(self) -> None:
        """Context uses the actual item nodeid - different nodeid produces different context."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_other.py::test_something_else'

        gen = plugin.pytest_runtest_call(item=item)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_other.py::test_something_else|run')


@pytest.mark.small
class DescribeGremlinContextPluginTeardown:
    """pytest_runtest_teardown switches context to ``{nodeid}|teardown``."""

    def it_switches_context_to_teardown_phase(self) -> None:
        """teardown hook switches coverage context to nodeid|teardown."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_foo.py::test_bar'

        gen = plugin.pytest_runtest_teardown(item=item)
        assert isinstance(gen, GeneratorType)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_foo.py::test_bar|teardown')

    def it_switches_context_using_item_nodeid(self) -> None:
        """Context uses the actual item nodeid - different nodeid produces different context."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_other.py::test_something_else'

        gen = plugin.pytest_runtest_teardown(item=item)
        next(gen)

        cov.switch_context.assert_called_once_with('tests/test_other.py::test_something_else|teardown')


@pytest.mark.small
class DescribeGremlinContextPluginPhaseDistinction:
    """Each phase produces a distinct context string."""

    def it_three_phases_produce_three_distinct_contexts(self) -> None:
        """setup, run and teardown each switch to a different context string."""
        cov = MagicMock(spec=coverage.Coverage)
        cov._started = True
        plugin = GremlinContextPlugin(cov)
        item = MagicMock(spec=pytest.Item)
        item.nodeid = 'tests/test_foo.py::test_bar'

        next(plugin.pytest_runtest_setup(item=item))
        next(plugin.pytest_runtest_call(item=item))
        next(plugin.pytest_runtest_teardown(item=item))

        assert cov.switch_context.call_args_list == [
            call('tests/test_foo.py::test_bar|setup'),
            call('tests/test_foo.py::test_bar|run'),
            call('tests/test_foo.py::test_bar|teardown'),
        ]
