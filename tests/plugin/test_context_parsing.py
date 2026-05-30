"""Tests for coverage context parsing in _extract_test_name_from_context.

The context format used by GremlinContextPlugin is:
    ``{nodeid}|{when}``  e.g. ``tests/test_foo.py::test_bar|run``

The function returns the full node ID (everything before ``|``) so that
tests with the same function name in different files are distinguishable.

The old dynamic_context=test_function format (without ``|``) is returned
as-is:
    ``test_bar``  -> ``test_bar``
    ``TestClass.test_method`` -> ``TestClass.test_method``
"""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _extract_test_name_from_context


@pytest.mark.small
class DescribeExtractTestNameFromContext:
    """_extract_test_name_from_context returns full node IDs for new format, passthrough for old."""

    def it_returns_full_nodeid_for_new_format_run_phase(self) -> None:
        """New format 'nodeid|run' returns the full node ID."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|run')
        assert result == 'tests/test_foo.py::test_bar'

    def it_returns_full_nodeid_for_new_format_setup_phase(self) -> None:
        """New format 'nodeid|setup' strips the phase, returns the full node ID."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|setup')
        assert result == 'tests/test_foo.py::test_bar'

    def it_returns_full_nodeid_for_new_format_teardown_phase(self) -> None:
        """New format 'nodeid|teardown' strips the phase, returns the full node ID."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|teardown')
        assert result == 'tests/test_foo.py::test_bar'

    def it_returns_full_nodeid_for_new_format_with_class(self) -> None:
        """New format with class preserves file::class::method in the result."""
        result = _extract_test_name_from_context('tests/test_foo.py::TestFoo::test_bar|run')
        assert result == 'tests/test_foo.py::TestFoo::test_bar'

    def it_produces_different_result_for_different_function_name(self) -> None:
        """Different node IDs produce different results - rules out hardcoding."""
        result_a = _extract_test_name_from_context('tests/test_foo.py::test_alpha|run')
        result_b = _extract_test_name_from_context('tests/test_foo.py::test_beta|run')
        assert result_a == 'tests/test_foo.py::test_alpha'
        assert result_b == 'tests/test_foo.py::test_beta'

    def it_returns_name_unchanged_for_old_format_plain_name(self) -> None:
        """Old dynamic_context format with plain function name passes through."""
        result = _extract_test_name_from_context('test_bar')
        assert result == 'test_bar'

    def it_returns_value_unchanged_for_old_format_dotted_name(self) -> None:
        """Old format 'TestClass.test_method' passes through unchanged."""
        result = _extract_test_name_from_context('TestClass.test_method')
        assert result == 'TestClass.test_method'

    def it_returns_value_unchanged_for_old_format_double_colon(self) -> None:
        """Old format 'path::test_func' (no pipe) passes through unchanged."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_func')
        assert result == 'tests/test_foo.py::test_func'

    def it_strips_only_the_trailing_phase_suffix_when_param_contains_pipe(self) -> None:
        """Parametrize values containing '|' must not be split mid-name.

        pytest node IDs like ``test_add[a|b-c]`` embed ``|`` inside the
        bracket expression.  Only the trailing ``|{when}`` suffix should be
        stripped — not any ``|`` inside the brackets.
        """
        result = _extract_test_name_from_context('tests/test_calc.py::test_add[a|b-c]|run')
        assert result == 'tests/test_calc.py::test_add[a|b-c]'

    def it_handles_multiple_pipes_in_param_value(self) -> None:
        """Multiple ``|`` characters inside brackets are all preserved."""
        result = _extract_test_name_from_context('tests/test_calc.py::test_add[a|b-c-a|bc]|run')
        assert result == 'tests/test_calc.py::test_add[a|b-c-a|bc]'

    def it_strips_setup_phase_when_param_contains_pipe(self) -> None:
        """The ``|setup`` suffix is stripped even when param value contains ``|``."""
        result = _extract_test_name_from_context('tests/test_calc.py::test_add[a|b]|setup')
        assert result == 'tests/test_calc.py::test_add[a|b]'

    def it_strips_teardown_phase_when_param_contains_pipe(self) -> None:
        """The ``|teardown`` suffix is stripped even when param value contains ``|``."""
        result = _extract_test_name_from_context('tests/test_calc.py::test_add[a|b]|teardown')
        assert result == 'tests/test_calc.py::test_add[a|b]'
