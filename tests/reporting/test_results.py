"""Tests for GremlinResult dataclass that tracks mutation test outcomes."""

from __future__ import annotations

import ast
import dataclasses

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
    limit_advice,
    mutant_timeout_advice,
)


@pytest.mark.small
class DescribeGremlinResultStatus:
    """Tests for GremlinResultStatus enum."""

    def it_status_has_zapped_value(self):
        assert GremlinResultStatus.ZAPPED.value == 'zapped'

    def it_status_has_survived_value(self):
        assert GremlinResultStatus.SURVIVED.value == 'survived'

    def it_status_has_timeout_value(self):
        assert GremlinResultStatus.TIMEOUT.value == 'timeout'

    def it_status_has_error_value(self):
        assert GremlinResultStatus.ERROR.value == 'error'

    def it_status_has_pardoned_value(self):
        assert GremlinResultStatus.PARDONED.value == 'pardoned'


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
class DescribeGremlinResultCreation:
    """Tests for GremlinResult dataclass creation and attributes."""

    def it_stores_gremlin(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.gremlin == sample_gremlin

    def it_stores_status(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.status == GremlinResultStatus.SURVIVED

    def it_stores_killing_test_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            killing_test='test_age_boundary',
        )
        assert result.killing_test == 'test_age_boundary'

    def it_result_killing_test_defaults_to_none(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.killing_test is None

    def it_stores_execution_time(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            execution_time_ms=42.5,
        )
        assert result.execution_time_ms == 42.5

    def it_result_execution_time_defaults_to_none(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.execution_time_ms is None

    def it_result_is_immutable(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        with pytest.raises(AttributeError):
            result.status = GremlinResultStatus.SURVIVED  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.small
class DescribeGremlinResultProperties:
    """Tests for computed properties on GremlinResult."""

    def it_is_zapped_returns_true_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.is_zapped is True

    def it_is_zapped_returns_false_when_survived(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.is_zapped is False

    def it_is_survived_returns_true_when_survived(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.is_survived is True

    def it_is_survived_returns_false_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.is_survived is False


@pytest.mark.small
class DescribeGremlinResultSelectedTests:
    """Tests for selected_tests field on GremlinResult."""

    def it_stores_selected_tests(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            selected_tests=['tests/test_a.py::test_foo', 'tests/test_b.py::test_bar'],
        )
        assert result.selected_tests == ['tests/test_a.py::test_foo', 'tests/test_b.py::test_bar']

    def it_defaults_selected_tests_to_empty_list(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.selected_tests == []

    def it_preserves_selected_tests_order(self, sample_gremlin):
        tests = ['tests/test_c.py::test_third', 'tests/test_a.py::test_first', 'tests/test_b.py::test_second']
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            selected_tests=tests,
        )
        assert result.selected_tests == tests


@pytest.mark.small
class DescribeGremlinResultReplacePreservesFields:
    """Tests that dataclasses.replace() preserves all fields when overriding selected_tests.

    Production code attaches selected_tests to a GremlinResult returned by
    _test_gremlin. Using dataclasses.replace() guarantees that any field added
    to GremlinResult in the future is preserved automatically, whereas manual
    reconstruction silently drops unknown fields.
    """

    def it_preserves_all_fields_when_attaching_selected_tests(self, sample_gremlin):
        original = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            killing_test='test_boundary',
            execution_time_ms=123.4,
            error_output='some stderr',
            selected_tests=[],
        )
        new_tests = ['tests/test_a.py::test_foo', 'tests/test_b.py::test_bar']

        replaced = dataclasses.replace(original, selected_tests=new_tests)

        assert replaced.selected_tests == new_tests
        assert replaced.gremlin is original.gremlin
        assert replaced.status is original.status
        assert replaced.killing_test == original.killing_test
        assert replaced.execution_time_ms == original.execution_time_ms
        assert replaced.error_output == original.error_output

    def it_only_overrides_selected_tests_field(self, sample_gremlin):
        original = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ERROR,
            killing_test=None,
            execution_time_ms=999.9,
            error_output='import failed',
            selected_tests=['old_test'],
        )

        replaced = dataclasses.replace(original, selected_tests=['new_test'])

        original_fields = {f.name: getattr(original, f.name) for f in dataclasses.fields(original)}
        replaced_fields = {f.name: getattr(replaced, f.name) for f in dataclasses.fields(replaced)}
        del original_fields['selected_tests']
        del replaced_fields['selected_tests']
        assert original_fields == replaced_fields


_MUTANT_RAISE = 'Raise {limit} with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout'


@pytest.mark.small
class DescribeLimitAdvice:
    """Tests for limit_advice, the remedy every timeout message names."""

    @pytest.mark.parametrize('attempt_timeout', [30, None])
    def it_names_the_limit_as_the_caller_does_when_it_was_not_scaled(self, attempt_timeout):
        advice = limit_advice(30, attempt_timeout, unscaled_name='it', raise_advice='raise {limit} now')

        assert advice == 'raise it now'

    def it_names_the_per_attempt_limit_when_it_was_scaled(self):
        advice = limit_advice(130, 30, unscaled_name='it', raise_advice='raise {limit} now')

        assert advice == 'raise the per-attempt limit now'

    def it_advises_lowering_the_reruns_when_scaling_reached_the_cap(self):
        advice = limit_advice(86400, 30000, unscaled_name='it', raise_advice='raise {limit} now')

        assert advice == 'the limit is capped at 86400s; lower --reruns or --reruns-delay'

    @pytest.mark.parametrize('attempt_timeout', [86400, None])
    def it_says_the_limit_is_at_the_maximum_when_it_was_configured_there(self, attempt_timeout):
        advice = limit_advice(86400, attempt_timeout, unscaled_name='it', raise_advice='raise {limit} now')

        assert advice == 'the limit is already at the 86400s maximum'

    def it_advises_raising_a_limit_one_second_below_the_maximum(self):
        advice = limit_advice(86399, None, unscaled_name='it', raise_advice='raise {limit} now')

        assert advice == 'raise it now'

    def it_advises_raising_a_limit_it_does_not_know(self):
        advice = limit_advice(None, None, unscaled_name='the timeout', raise_advice='raise {limit} now')

        assert advice == 'raise the timeout now'


@pytest.mark.small
class DescribeMutantTimeoutAdvice:
    """Tests for mutant_timeout_advice, the closing sentence of the downgraded-timeout messages."""

    def it_offers_raising_the_limit_or_speeding_up_the_tests(self):
        advice = mutant_timeout_advice(30, None, unscaled_name='the limit', tests='these tests')

        assert advice == (f'{_MUTANT_RAISE.format(limit="the limit")}, or speed up these tests.')

    def it_names_the_per_attempt_limit_when_it_was_scaled(self):
        advice = mutant_timeout_advice(130, 30, unscaled_name='the limit', tests='those tests')

        assert advice == (f'{_MUTANT_RAISE.format(limit="the per-attempt limit")}, or speed up those tests.')

    def it_offers_lowering_the_reruns_when_scaling_reached_the_cap(self):
        advice = mutant_timeout_advice(86400, 30000, unscaled_name='the limit', tests='these tests')

        assert advice == 'The limit is capped at 86400s; lower --reruns or --reruns-delay, or speed up these tests.'

    def it_leaves_only_speeding_up_when_the_limit_was_configured_at_the_maximum(self):
        advice = mutant_timeout_advice(86400, 86400, unscaled_name='the limit', tests='these tests')

        assert advice == 'The limit is already at the 86400s maximum, so speed up these tests.'
