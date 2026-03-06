"""Tests for _workers_type argparse type function."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from pytest_gremlins.plugin import _workers_type


@pytest.mark.small
class DescribeWorkersType:
    """Tests for the _workers_type argument parser helper."""

    def it_returns_cpu_count_for_auto(self) -> None:
        """'auto' resolves to os.cpu_count() when cpu_count is available."""
        with patch('os.cpu_count', return_value=8):
            assert _workers_type('auto') == 8

    def it_falls_back_to_4_when_cpu_count_is_none(self) -> None:
        """'auto' falls back to 4 when os.cpu_count() returns None."""
        with patch('os.cpu_count', return_value=None):
            assert _workers_type('auto') == 4

    def it_parses_a_numeric_string_as_int(self) -> None:
        """A numeric string is parsed as an integer."""
        assert _workers_type('2') == 2

    def it_raises_argument_type_error_for_invalid_input(self) -> None:
        """A non-numeric, non-'auto' string raises argparse.ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            _workers_type('invalid')

    def it_raises_argument_type_error_for_zero(self) -> None:
        """Zero is not a valid worker count and raises argparse.ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            _workers_type('0')

    def it_raises_argument_type_error_for_negative_integer(self) -> None:
        """A negative integer is not a valid worker count and raises argparse.ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            _workers_type('-1')
