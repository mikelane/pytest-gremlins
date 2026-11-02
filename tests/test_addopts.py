"""Tests for the shared ``PYTEST_ADDOPTS`` parse."""

from __future__ import annotations

import pytest

from pytest_gremlins.addopts import (
    inherited_addopts_tokens,
    split_addopts,
)


@pytest.mark.small
class DescribeSplitAddopts:
    def it_removes_quoting_from_tokens(self) -> None:
        assert split_addopts('-k "a or b" -v') == ['-k', 'a or b', '-v']

    def it_returns_no_tokens_for_an_empty_string(self) -> None:
        assert split_addopts('') == []

    def it_raises_on_unbalanced_quotes(self) -> None:
        with pytest.raises(ValueError, match='No closing quotation'):
            split_addopts('-k "unbalanced')


@pytest.mark.small
class DescribeInheritedAddoptsTokens:
    def it_splits_the_variable_with_quoting(self) -> None:
        assert inherited_addopts_tokens({'PYTEST_ADDOPTS': "-x -k 'a or b'"}) == ['-x', '-k', 'a or b']

    def it_returns_no_tokens_for_an_empty_value(self) -> None:
        assert inherited_addopts_tokens({'PYTEST_ADDOPTS': ''}) == []

    def it_returns_no_tokens_when_the_variable_is_unset(self) -> None:
        assert inherited_addopts_tokens({}) == []

    def it_returns_no_tokens_for_unbalanced_quotes(self) -> None:
        assert inherited_addopts_tokens({'PYTEST_ADDOPTS': '-k "unbalanced'}) == []
