"""Gremlin dataclass representing a single mutation.

A Gremlin is a mutation injected into code. It contains all information needed
to identify and activate the mutation during test execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Protocol,
    runtime_checkable,
)


if TYPE_CHECKING:
    import ast


@runtime_checkable
class ASTLocated(Protocol):
    """Protocol for AST nodes that carry source location information.

    All ``ast.expr`` and ``ast.stmt`` nodes satisfy this protocol.
    Use it when you only need location attributes and want to avoid
    an unsafe ``cast``.
    """

    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None


@dataclass(frozen=True)
class Gremlin:
    """A mutation (gremlin) injected into source code.

    Attributes:
        gremlin_id: Unique identifier for this gremlin (e.g., 'g001').
        file_path: Path to the source file containing this mutation.
        line_number: Line number where the mutation occurs.
        original_node: The original AST node before mutation.
        mutated_node: The mutated AST node.
        operator_name: Name of the operator that created this mutation.
        description: Human-readable description of the mutation.
    """

    gremlin_id: str
    file_path: str
    line_number: int
    original_node: ast.expr | ast.stmt
    mutated_node: ast.expr | ast.stmt
    operator_name: str
    description: str
