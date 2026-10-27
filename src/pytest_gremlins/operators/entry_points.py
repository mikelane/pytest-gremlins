"""Load third-party operators from the ``pytest_gremlins.operators`` entry-point group.

A package ships operators by declaring an entry point whose target is a callable
``register(registry: OperatorRegistry) -> None``. Each callable receives a scratch
registry; only if it succeeds are its operators merged into the target registry.
"""

from __future__ import annotations

from collections.abc import Callable
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

_registered_by_loader: dict[str, tuple[type[GremlinOperator], str]] = {}


class GremlinEntryPointWarning(UserWarning):
    """A third-party operator entry point failed to load or collided with an existing operator."""


def discard_warning(_message: str) -> None:
    """Drop a warning message; pass as ``warn`` to load operators silently."""


def _describe(entry_point: EntryPoint) -> str:
    distribution = entry_point.dist.name if entry_point.dist is not None else 'unknown distribution'
    return f"entry point '{entry_point.name}' from '{distribution}'"


WarnCallback = Callable[[str], None]


def warn_with_python_warnings(message: str) -> None:
    """Emit ``message`` as a ``GremlinEntryPointWarning`` attributed to the caller of the loader."""
    warnings.warn(message, GremlinEntryPointWarning, stacklevel=4)


def _run_into_scratch(entry_point: EntryPoint, *, warn: WarnCallback) -> OperatorRegistry | None:
    scratch = OperatorRegistry()
    try:
        register = entry_point.load()
        if not callable(register):
            warn(f'{_describe(entry_point)} is not callable, ignoring')
            return None
        register(scratch)
    except Exception as failure:
        warn(f'{_describe(entry_point)} failed to load, ignoring: {failure}')
        return None
    return scratch


def _source_of(entry_point: EntryPoint) -> str:
    return _describe(entry_point) + f' -> {entry_point.value}'


def _is_own_earlier_registration(
    name: str, entry_point: EntryPoint, target: OperatorRegistry, claimed_this_load: set[str]
) -> bool:
    if name in claimed_this_load or name not in _registered_by_loader:
        return False
    registered_class, registered_source = _registered_by_loader[name]
    return registered_source == _source_of(entry_point) and target.get_class(name) is registered_class


def _merge(
    scratch: OperatorRegistry,
    target: OperatorRegistry,
    entry_point: EntryPoint,
    *,
    claimed_this_load: set[str],
    warn: WarnCallback,
) -> None:
    for name in scratch.available():
        operator_class = scratch.get_class(name)
        if name in target.available():
            if _is_own_earlier_registration(name, entry_point, target, claimed_this_load):
                claimed_this_load.add(name)
                continue
            warn(f"operator '{name}' from {_describe(entry_point)} is already registered, keeping the existing one")
            continue
        target.register(operator_class, name=name)
        _registered_by_loader[name] = (operator_class, _source_of(entry_point))
        claimed_this_load.add(name)


def load_entry_point_operators(registry: OperatorRegistry, *, warn: WarnCallback = warn_with_python_warnings) -> None:
    """Register operators declared by installed packages into ``registry``.

    Args:
        registry: The registry to merge discovered operators into.
        warn: Called with a message for each broken entry point or name collision.
    """
    claimed_this_load: set[str] = set()
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        scratch = _run_into_scratch(entry_point, warn=warn)
        if scratch is not None:
            _merge(scratch, registry, entry_point, claimed_this_load=claimed_this_load, warn=warn)
