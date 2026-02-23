"""Tests for coverage context parsing in _extract_test_name_from_context.

The context format used by GremlinContextPlugin is:
    ``{nodeid}|{when}``  e.g. ``tests/test_foo.py::test_bar|run``

The nodeid part is ``tests/test_foo.py::test_bar`` and the function name is
extracted as the last ``::``-separated segment: ``test_bar``.

The old dynamic_context=test_function format (without ``|``) is also handled
as a fallback:
    ``test_bar``  -> ``test_bar``
    ``TestClass.test_method`` -> ``test_method``
"""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _extract_test_name_from_context


@pytest.mark.small
class DescribeExtractTestNameFromContext:
    """_extract_test_name_from_context parses both old and new context formats."""

    def it_returns_function_name_for_new_format_run_phase(self) -> None:
        """New format 'nodeid|run' returns the test function name."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|run')
        assert result == 'test_bar'

    def it_returns_function_name_for_new_format_setup_phase(self) -> None:
        """New format 'nodeid|setup' still returns the test function name, not 'setup'."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|setup')
        assert result == 'test_bar'

    def it_returns_function_name_for_new_format_teardown_phase(self) -> None:
        """New format 'nodeid|teardown' still returns the test function name."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_bar|teardown')
        assert result == 'test_bar'

    def it_returns_method_name_for_new_format_with_class(self) -> None:
        """New format with class::method extracts the method name."""
        result = _extract_test_name_from_context('tests/test_foo.py::TestFoo::test_bar|run')
        assert result == 'test_bar'

    def it_produces_different_result_for_different_function_name(self) -> None:
        """Different function names produce different results - rules out hardcoding."""
        result_a = _extract_test_name_from_context('tests/test_foo.py::test_alpha|run')
        result_b = _extract_test_name_from_context('tests/test_foo.py::test_beta|run')
        assert result_a == 'test_alpha'
        assert result_b == 'test_beta'

    def it_returns_name_unchanged_for_old_format_plain_name(self) -> None:
        """Old dynamic_context format with plain function name passes through."""
        result = _extract_test_name_from_context('test_bar')
        assert result == 'test_bar'

    def it_returns_last_segment_for_old_format_dotted_name(self) -> None:
        """Old format 'Module.test_method' returns just 'test_method'."""
        result = _extract_test_name_from_context('TestClass.test_method')
        assert result == 'test_method'

    def it_returns_last_segment_for_old_format_double_colon(self) -> None:
        """Old format 'path::test_func' (no pipe) returns 'test_func'."""
        result = _extract_test_name_from_context('tests/test_foo.py::test_func')
        assert result == 'test_func'
