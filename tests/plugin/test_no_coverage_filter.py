"""Tests for --gremlin-no-coverage-filter CLI option."""

from __future__ import annotations

import ast
from unittest.mock import (
    MagicMock,
    create_autospec,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _select_tests_for_gremlin_prioritized,
    pytest_addoption,
)


@pytest.mark.small
class DescribeNoCoverageFilterOption:
    """Tests that --gremlin-no-coverage-filter CLI option is registered."""

    def it_registers_gremlin_no_coverage_filter_option(self):
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-no-coverage-filter' in added_option_names


@pytest.mark.small
class DescribeGremlinSessionNoCoverageFilter:
    """Tests for no_coverage_filter field on GremlinSession."""

    def it_defaults_no_coverage_filter_to_false(self):
        session = GremlinSession()
        assert session.no_coverage_filter is False

    def it_accepts_no_coverage_filter_true(self):
        session = GremlinSession(no_coverage_filter=True)
        assert session.no_coverage_filter is True


@pytest.fixture
def sample_gremlin():
    return Gremlin(
        gremlin_id='g001',
        file_path='src/auth.py',
        line_number=42,
        original_node=ast.parse('age >= 18', mode='eval').body,
        mutated_node=ast.parse('age > 18', mode='eval').body,
        operator_name='comparison',
        description='>= to >',
    )


@pytest.mark.small
class DescribeSelectTestsWithNoCoverageFilter:
    """Tests that no_coverage_filter bypasses coverage-guided selection."""

    def it_returns_all_tests_when_no_coverage_filter_is_true(self, sample_gremlin):
        mock_selector = create_autospec(PrioritizedSelector, instance=True)
        mock_selector.select_tests_prioritized.return_value = ['test_specific']
        session = GremlinSession(
            test_node_ids={'test_a': 'tests/test_a.py::test_a', 'test_b': 'tests/test_b.py::test_b'},
            prioritized_selector=mock_selector,
            no_coverage_filter=True,
        )

        result = _select_tests_for_gremlin_prioritized(sample_gremlin, session)

        assert sorted(result) == ['test_a', 'test_b']
        mock_selector.select_tests_prioritized.assert_not_called()

    def it_uses_prioritized_selector_when_no_coverage_filter_is_false(self, sample_gremlin):
        mock_selector = create_autospec(PrioritizedSelector, instance=True)
        mock_selector.select_tests_prioritized.return_value = ['test_specific']
        session = GremlinSession(
            test_node_ids={'test_a': 'tests/test_a.py::test_a', 'test_b': 'tests/test_b.py::test_b'},
            prioritized_selector=mock_selector,
            no_coverage_filter=False,
        )

        result = _select_tests_for_gremlin_prioritized(sample_gremlin, session)

        assert result == ['test_specific']
        mock_selector.select_tests_prioritized.assert_called_once_with(sample_gremlin)
