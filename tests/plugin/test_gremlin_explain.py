"""Tests for --gremlin-explain diagnostic CLI option.

Covers PR 1 of issue #397's two-PR sequence: a read-only diagnostic that
surfaces drift between the coverage map and the selected test list for a
single gremlin, without modifying selection or coverage collection.
"""

from __future__ import annotations

import ast
from contextlib import redirect_stdout
import io
from unittest.mock import (
    MagicMock,
    create_autospec,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.coverage.collector import CoverageCollector
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _emit_selection_explainer,
    pytest_addoption,
)


@pytest.mark.small
class DescribeGremlinExplainOption:
    """Tests that --gremlin-explain CLI option is registered."""

    def it_registers_gremlin_explain_option(self):
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-explain' in added_option_names


@pytest.mark.small
class DescribeGremlinSessionExplainGremlinId:
    """Tests for explain_gremlin_id field on GremlinSession."""

    def it_defaults_explain_gremlin_id_to_none(self):
        session = GremlinSession()
        assert session.explain_gremlin_id is None

    def it_accepts_explain_gremlin_id_string(self):
        session = GremlinSession(explain_gremlin_id='g042')
        assert session.explain_gremlin_id == 'g042'


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


def _build_session_with_drift(sample_gremlin: Gremlin) -> GremlinSession:
    """Build a GremlinSession whose coverage-map key drifts from test_node_ids.

    The coverage map records a key with a ``[custom-tag]`` marker suffix
    (lowercase-hyphen — the current ``[A-Z]+`` regex in
    ``_make_node_ids_relative`` leaves it alone). The ``test_node_ids`` dict
    stores the same test *without* the suffix, producing a one-token drift
    between the two key spaces. This is the exact shape of the #387 bug.
    """
    collector = CoverageCollector()
    drifted_key = 'tests/test_target.py::test_zero_case [custom-tag]'
    collector.record_test_coverage(
        drifted_key,
        {sample_gremlin.file_path: [sample_gremlin.line_number]},
    )

    mock_selector = create_autospec(PrioritizedSelector, instance=True)
    mock_selector.select_tests_prioritized.return_value = []

    return GremlinSession(
        enabled=True,
        gremlins=[sample_gremlin],
        test_node_ids={
            'tests/test_target.py::test_nonzero_case': 'tests/test_target.py::test_nonzero_case',
            'tests/test_target.py::test_zero_case': 'tests/test_target.py::test_zero_case',
        },
        coverage_collector=collector,
        prioritized_selector=mock_selector,
        explain_gremlin_id=sample_gremlin.gremlin_id,
    )


@pytest.mark.small
class DescribeEmitSelectionExplainerDrift:
    """Tests that the explainer surfaces node-ID drift when it exists."""

    def it_prints_covering_and_selected_sets_when_drift_exists(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        assert sample_gremlin.gremlin_id in output
        assert 'Covering set' in output
        assert 'Selected' in output

    def it_names_the_dropped_test_in_the_diff(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        assert 'tests/test_target.py::test_zero_case [custom-tag]' in output

    def it_suggests_close_match_for_drifted_key(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        assert 'tests/test_target.py::test_zero_case' in output
        assert 'close match' in output.lower() or 'close_match' in output.lower()

    def it_disables_gremlin_session_after_emitting(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)
        assert session.enabled is True

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        assert session.enabled is False


@pytest.mark.small
class DescribeEmitSelectionExplainerNoDrift:
    """Tests the explainer reports a clean run when coverage and selection agree."""

    def it_reports_selection_is_consistent_when_no_drift(self, sample_gremlin):
        collector = CoverageCollector()
        aligned_key = 'tests/test_target.py::test_zero_case'
        collector.record_test_coverage(
            aligned_key,
            {sample_gremlin.file_path: [sample_gremlin.line_number]},
        )

        mock_selector = create_autospec(PrioritizedSelector, instance=True)
        mock_selector.select_tests_prioritized.return_value = [aligned_key]

        session = GremlinSession(
            enabled=True,
            gremlins=[sample_gremlin],
            test_node_ids={aligned_key: aligned_key},
            coverage_collector=collector,
            prioritized_selector=mock_selector,
            explain_gremlin_id=sample_gremlin.gremlin_id,
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        assert 'consistent' in output.lower()


@pytest.mark.small
class DescribeEmitSelectionExplainerMissingGremlin:
    """Tests behaviour when the requested gremlin_id is not in the session."""

    def it_reports_unknown_gremlin_id_and_disables_session(self, sample_gremlin):
        collector = CoverageCollector()
        mock_selector = create_autospec(PrioritizedSelector, instance=True)
        mock_selector.select_tests_prioritized.return_value = []

        session = GremlinSession(
            enabled=True,
            gremlins=[sample_gremlin],
            test_node_ids={},
            coverage_collector=collector,
            prioritized_selector=mock_selector,
            explain_gremlin_id='nonexistent_gremlin_id',
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        assert 'nonexistent_gremlin_id' in output
        assert session.enabled is False


@pytest.mark.small
class DescribeEmitSelectionExplainerNotRequested:
    """Tests that the explainer no-ops when the user did not request it."""

    def it_does_nothing_when_explain_gremlin_id_is_none(self, sample_gremlin):
        session = GremlinSession(
            enabled=True,
            gremlins=[sample_gremlin],
            explain_gremlin_id=None,
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        assert buffer.getvalue() == ''
        assert session.enabled is True
