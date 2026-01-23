"""Central registry for gremlin operators.

This module provides the OperatorRegistry class which manages
the discovery and instantiation of mutation operators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import warnings


if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_gremlins.operators.protocol import GremlinOperator


class OperatorRegistry:
    """Central registry for gremlin operators.

    This class manages the registration and retrieval of mutation operators.
    Operators are registered by their name and can be retrieved individually
    or as a group.

    Example:
        >>> from pytest_gremlins.operators import ComparisonOperator
        >>> registry = OperatorRegistry()
        >>> registry.register(ComparisonOperator)
        >>> 'comparison' in registry.available()
        True
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._operators: dict[str, type[GremlinOperator]] = {}

    def register(
        self,
        operator_class: type[GremlinOperator],
        name: str | None = None,
    ) -> None:
        """Register an operator class.

        Args:
            operator_class: The operator class to register.
            name: Optional name to register under. If not provided,
                  uses the operator's name property.
        """
        key = name if name is not None else operator_class().name
        self._operators[key] = operator_class

    def register_decorator(
        self,
        name: str | None = None,
    ) -> Callable[[type[GremlinOperator]], type[GremlinOperator]]:
        """Decorator to register an operator class.

        Args:
            name: Optional name to register under.

        Returns:
            Decorator function that registers the class.

        Example:
            >>> registry = OperatorRegistry()
            >>> @registry.register_decorator('comparison')
            ... class ComparisonOperator:
            ...     ...
        """

        def decorator(operator_class: type[GremlinOperator]) -> type[GremlinOperator]:
            self.register(operator_class, name=name)
            return operator_class

        return decorator

    def get(self, name: str) -> GremlinOperator:
        """Get a single operator by name.

        Args:
            name: The registered name of the operator.

        Returns:
            An instance of the requested operator.

        Raises:
            KeyError: If no operator is registered with the given name.
        """
        if name not in self._operators:
            raise KeyError(f"Unknown operator: '{name}'")
        return self._operators[name]()

    def get_all(self, enabled: list[str] | None = None) -> list[GremlinOperator]:
        """Get operator instances.

        Args:
            enabled: If provided, only return these operators (in order).
                     If None, return all registered operators.

        Returns:
            List of operator instances.
        """
        if enabled is None:
            return [op() for op in self._operators.values()]

        operators: list[GremlinOperator] = []
        for name in enabled:
            if name in self._operators:
                operators.append(self._operators[name]())
            else:
                warnings.warn(f"Unknown operator '{name}' requested, ignoring", UserWarning, stacklevel=2)
        return operators

    def available(self) -> list[str]:
        """List all registered operator names.

        Returns:
            List of registered operator names.
        """
        return list(self._operators.keys())
