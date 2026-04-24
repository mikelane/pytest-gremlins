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

from pytest_gremlins.coverage import (
    CoverageCollector,
    PrioritizedSelector,
)
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

        # Locate the specific addoption call for --gremlin-explain so we can
        # verify the registered shape, not just the presence of the flag name.
        explain_calls = [call for call in group.addoption.call_args_list if call.args[0] == '--gremlin-explain']
        assert len(explain_calls) == 1
        explain_kwargs = explain_calls[0].kwargs
        # Must default to ``None`` so the explainer no-ops when the flag is absent.
        assert explain_kwargs.get('default') is None
        # The value is consumed via ``getoption('gremlin_explain')``; a renamed
        # dest would silently break the CLI without this assertion catching it.
        assert explain_kwargs.get('dest') == 'gremlin_explain'
        # ``action='store'`` (the default) is what makes ``--gremlin-explain=<id>``
        # capture the argument rather than behave as a boolean flag.
        assert explain_kwargs.get('action', 'store') == 'store'
        # Flag must carry a non-empty help string so ``--help`` shows it to users.
        assert isinstance(explain_kwargs.get('help'), str)
        assert explain_kwargs['help']


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

    # Simulate the exact shape of the #387 bug: the selector returns the
    # non-drifted test (a valid runnable key) but silently drops the drifted
    # key, so ``covering_minus_selected`` is a single-element set naming the
    # lost killer.
    mock_selector = create_autospec(PrioritizedSelector, instance=True)
    mock_selector.select_tests_prioritized.return_value = ['tests/test_target.py::test_nonzero_case']

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
        # Banner identifies the gremlin under inspection.
        assert f'--gremlin-explain: diagnostic for {sample_gremlin.gremlin_id}' in output
        # Header echoes the mutated file and line so a reader can confirm the
        # diagnostic corresponds to the right source location.
        assert f'  file: {sample_gremlin.file_path}:{sample_gremlin.line_number}' in output
        # Covering set shows the drifted key and its exact count.
        assert 'Covering set (1 test(s)):' in output
        assert "'tests/test_target.py::test_zero_case [custom-tag]'" in output
        # Selected list contains the non-drifted test; the drifted key was
        # silently dropped by the (simulated) selector — the exact #387 shape.
        assert 'Selected list (1 test(s)):' in output
        assert "'tests/test_target.py::test_nonzero_case'" in output

    def it_names_the_dropped_test_in_the_diff(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        # The drifted key must appear specifically in the "Covering minus selected" section,
        # not merely in the header echo of the covering set.
        _, dropped_section = output.split('Covering minus selected', 1)
        assert "dropped    : 'tests/test_target.py::test_zero_case [custom-tag]'" in dropped_section
        assert "stripped   : 'tests/test_target.py::test_zero_case'" in dropped_section

    def it_suggests_close_match_for_drifted_key(self, sample_gremlin):
        session = _build_session_with_drift(sample_gremlin)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _emit_selection_explainer(session)

        output = buffer.getvalue()
        # The close-match line must name the intended runnable key, not just the label.
        _, dropped_section = output.split('Covering minus selected', 1)
        assert "close match: 'tests/test_target.py::test_zero_case'" in dropped_section

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
        # Exact contract: banner, then the structured "no drift" result line.
        assert f'--gremlin-explain: diagnostic for {sample_gremlin.gremlin_id}' in output
        assert '  Result: selection is consistent with covering set (no drift).' in output
        # Covering set header shows the exact count, not a hand-wave.
        assert 'Covering set (1 test(s)):' in output
        assert 'Selected list (1 test(s)):' in output
        # No drift means no dropped-test breakdown is emitted.
        assert 'Covering minus selected' not in output
        assert 'Selected but not in test_node_ids' not in output
        # Session must be disabled so the per-gremlin loop short-circuits.
        assert session.enabled is False


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
        # Exact banner — quoting the id via ``!r`` is part of the contract so a
        # mutation that dropped the repr would not silently pass.
        assert "--gremlin-explain: no gremlin with id 'nonexistent_gremlin_id' in this session." in output
        # None of the drift-breakdown sections should appear for an unknown id.
        assert 'Covering set' not in output
        assert 'Selected list' not in output
        assert 'Covering minus selected' not in output
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
