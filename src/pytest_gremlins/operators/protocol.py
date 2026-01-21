"""Protocol definition for mutation operators.

All mutation operators must implement the GremlinOperator protocol.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Protocol,
    runtime_checkable,
)


if TYPE_CHECKING:
    import ast


@runtime_checkable
class GremlinOperator(Protocol):
    """Protocol for all mutation operators.

    A GremlinOperator identifies specific AST patterns and generates
    mutated variants (gremlins) of those patterns.

    Attributes:
        name: Unique identifier for this operator (e.g., 'comparison', 'arithmetic').
        description: Human-readable description for reports.
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        ...

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        ...

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this operator can generate mutations for this node.
        """
        ...

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Each returned AST node represents one gremlin (mutation).

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes, one for each possible mutation.
        """
        ...
