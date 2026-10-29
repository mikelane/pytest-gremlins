"""Tests for OperatorRegistry.get_class."""

from __future__ import annotations

import pytest

from pytest_gremlins.operators import (
    ComparisonOperator,
    OperatorRegistry,
)


@pytest.mark.small
class DescribeGetClass:
    def it_returns_the_registered_class_not_an_instance(self) -> None:
        registry = OperatorRegistry()
        registry.register(ComparisonOperator)

        assert registry.get_class('comparison') is ComparisonOperator

    def it_returns_the_class_registered_under_a_custom_name(self) -> None:
        registry = OperatorRegistry()
        registry.register(ComparisonOperator, name='alias')

        assert registry.get_class('alias') is ComparisonOperator

    def it_raises_key_error_for_unknown_name(self) -> None:
        registry = OperatorRegistry()

        with pytest.raises(KeyError, match='ghost'):
            registry.get_class('ghost')
