"""Load third-party operators from the ``pytest_gremlins.operators`` entry-point group.

A package ships operators by declaring an entry point whose target is a callable
``register(registry: OperatorRegistry) -> None``. Each callable receives a scratch
registry; only if it succeeds are its operators merged into the target registry.
"""

from __future__ import annotations

from importlib.metadata import (
    EntryPoint,
    entry_points,
)
from typing import TYPE_CHECKING
import warnings

from pytest_gremlins.operators.registry import OperatorRegistry

if TYPE_CHECKING:
    from pytest_gremlins.operators.protocol import GremlinOperator

ENTRY_POINT_GROUP = 'pytest_gremlins.operators'

_registered_by_loader: dict[str, type[GremlinOperator]] = {}


class GremlinEntryPointWarning(UserWarning):
    """A third-party operator entry point failed to load or collided with an existing operator."""


def _describe(entry_point: EntryPoint) -> str:
    distribution = entry_point.dist.name if entry_point.dist is not None else 'unknown distribution'
    return f"entry point '{entry_point.name}' from '{distribution}'"


def _warn(message: str, *, emit_warnings: bool) -> None:
    if emit_warnings:
        warnings.warn(message, GremlinEntryPointWarning, stacklevel=3)


def _run_into_scratch(entry_point: EntryPoint, *, emit_warnings: bool) -> OperatorRegistry | None:
    scratch = OperatorRegistry()
    try:
        register = entry_point.load()
        if not callable(register):
            _warn(f'{_describe(entry_point)} is not callable, ignoring', emit_warnings=emit_warnings)
            return None
        register(scratch)
    except Exception as failure:
        _warn(
            f'{_describe(entry_point)} failed to load, ignoring: {failure}',
            emit_warnings=emit_warnings,
        )
        return None
    return scratch


def _merge(
    scratch: OperatorRegistry,
    target: OperatorRegistry,
    entry_point: EntryPoint,
    *,
    claimed_this_load: set[str],
    emit_warnings: bool,
) -> None:
    for name in scratch.available():
        operator_class = scratch.get_class(name)
        if name in target.available():
            if name not in claimed_this_load and _registered_by_loader.get(name) is target.get_class(name):
                continue
            _warn(
                f"operator '{name}' from {_describe(entry_point)} is already registered, keeping the existing one",
                emit_warnings=emit_warnings,
            )
            continue
        target.register(operator_class, name=name)
        _registered_by_loader[name] = operator_class
        claimed_this_load.add(name)


def load_entry_point_operators(registry: OperatorRegistry, *, emit_warnings: bool = True) -> None:
    """Register operators declared by installed packages into ``registry``.

    Args:
        registry: The registry to merge discovered operators into.
        emit_warnings: When False, broken entry points and name collisions are skipped silently.
    """
    claimed_this_load: set[str] = set()
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        scratch = _run_into_scratch(entry_point, emit_warnings=emit_warnings)
        if scratch is not None:
            _merge(scratch, registry, entry_point, claimed_this_load=claimed_this_load, emit_warnings=emit_warnings)
