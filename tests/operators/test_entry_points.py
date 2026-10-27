"""Tests for loading third-party operators from the ``pytest_gremlins.operators`` entry-point group."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import warnings

import pytest

from pytest_gremlins.operators import (
    ComparisonOperator,
    GremlinEntryPointWarning,
    OperatorRegistry,
)
from pytest_gremlins.operators.entry_points import load_entry_point_operators

CONSTANT_OPERATOR_MODULE = """
import ast


class EpConstantOperator:
    name = 'ep-constant'
    description = 'test operator'

    def can_mutate(self, node):
        return isinstance(node, ast.Constant)

    def mutate(self, node):
        return []


def register(registry):
    registry.register(EpConstantOperator)
"""

Installer = Callable[..., Path]


def _load(registry: OperatorRegistry, *, emit_warnings: bool = True) -> list[warnings.WarningMessage]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        load_entry_point_operators(registry, emit_warnings=emit_warnings)
    return [w for w in caught if issubclass(w.category, GremlinEntryPointWarning)]


@pytest.mark.medium
class DescribeLoadEntryPointOperators:
    def it_registers_operators_from_an_installed_distribution(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist({'ep': 'ep_mod:register'}, {'ep_mod': CONSTANT_OPERATOR_MODULE})
        registry = OperatorRegistry()

        caught = _load(registry)

        assert registry.available() == ['ep-constant']
        assert caught == []

    def it_warns_and_continues_when_the_module_fails_to_import(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist(
            {'bad': 'missing_mod_xyz:register', 'good': 'ep_mod:register'},
            {'ep_mod': CONSTANT_OPERATOR_MODULE},
        )
        registry = OperatorRegistry()

        caught = _load(registry)

        assert len(caught) == 1
        message = str(caught[0].message)
        assert 'bad' in message
        assert 'gremlin_ep_dist' in message
        assert 'missing_mod_xyz' in message
        assert registry.available() == ['ep-constant']

    def it_warns_with_the_exception_message_when_the_callable_raises(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist(
            {'boom': 'boom_mod:register'},
            {'boom_mod': 'def register(registry):\n    raise RuntimeError("kaput")\n'},
        )

        caught = _load(OperatorRegistry())

        assert len(caught) == 1
        assert 'kaput' in str(caught[0].message)
        assert 'boom' in str(caught[0].message)

    def it_warns_when_the_loaded_object_is_not_callable(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist({'plain': 'plain_mod:register'}, {'plain_mod': 'register = 42\n'})

        caught = _load(OperatorRegistry())

        assert len(caught) == 1
        assert 'is not callable' in str(caught[0].message)

    def it_discards_operators_registered_before_the_callable_raised(self, install_entry_point_dist: Installer) -> None:
        source = (
            CONSTANT_OPERATOR_MODULE
            + "\ndef register_then_fail(registry):\n    register(registry)\n    raise RuntimeError('late')\n"
        )
        install_entry_point_dist({'partial': 'ep_mod:register_then_fail'}, {'ep_mod': source})
        registry = OperatorRegistry()

        _load(registry)

        assert registry.available() == []

    def it_does_not_warn_when_the_callable_registers_nothing(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist({'noop': 'noop_mod:register'}, {'noop_mod': 'def register(registry):\n    pass\n'})

        assert _load(OperatorRegistry()) == []

    def it_keeps_an_existing_operator_and_warns_on_name_collision(self, install_entry_point_dist: Installer) -> None:
        source = CONSTANT_OPERATOR_MODULE.replace("'ep-constant'", "'comparison'")
        install_entry_point_dist({'shadow': 'ep_mod:register'}, {'ep_mod': source})
        registry = OperatorRegistry()
        registry.register(ComparisonOperator)

        caught = _load(registry)

        assert registry.get_class('comparison') is ComparisonOperator
        assert len(caught) == 1
        assert 'comparison' in str(caught[0].message)
        assert 'shadow' in str(caught[0].message)

    def it_stays_silent_when_reloading_what_it_registered_itself(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist({'ep': 'ep_mod:register'}, {'ep_mod': CONSTANT_OPERATOR_MODULE})
        registry = OperatorRegistry()
        _load(registry)

        caught = _load(registry)

        assert caught == []
        assert registry.available() == ['ep-constant']

    def it_warns_when_something_replaced_the_operator_the_loader_registered(
        self, install_entry_point_dist: Installer
    ) -> None:
        install_entry_point_dist({'ep': 'ep_mod:register'}, {'ep_mod': CONSTANT_OPERATOR_MODULE})
        registry = OperatorRegistry()
        _load(registry)
        registry.register(ComparisonOperator, name='ep-constant')

        caught = _load(registry)

        assert len(caught) == 1
        assert registry.get_class('ep-constant') is ComparisonOperator

    def it_lets_the_first_distribution_win_between_entry_points(self, install_entry_point_dist: Installer) -> None:
        second = CONSTANT_OPERATOR_MODULE.replace('EpConstantOperator', 'Other')
        install_entry_point_dist(
            {'first': 'ep_mod:register', 'second': 'ep_mod2:register'},
            {'ep_mod': CONSTANT_OPERATOR_MODULE, 'ep_mod2': second},
        )
        registry = OperatorRegistry()

        caught = _load(registry)

        assert registry.get_class('ep-constant').__name__ == 'EpConstantOperator'
        assert len(caught) == 1
        assert 'second' in str(caught[0].message)

    def it_emits_no_warnings_when_told_not_to(self, install_entry_point_dist: Installer) -> None:
        install_entry_point_dist({'plain': 'plain_mod:register'}, {'plain_mod': 'register = 42\n'})

        assert _load(OperatorRegistry(), emit_warnings=False) == []
