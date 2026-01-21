"""Boolean mutation operator.

This operator mutates boolean operators and values (and/or, True/False, not).
"""

from __future__ import annotations

import ast
import copy


class BooleanOperator:
    """Mutate boolean operators and values.

    Generates mutations for boolean logic to catch logic errors.

    Mutations:
        - and -> or
        - or -> and
        - not x -> x
        - True -> False
        - False -> True
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'boolean'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Swap boolean operators and values (and/or, True/False, not x -> x)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a boolean operation or value we can mutate.
        """
        if isinstance(node, ast.BoolOp):
            return True

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return True

        return isinstance(node, ast.Constant) and isinstance(node.value, bool)

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes, one for each possible mutation.
        """
        if isinstance(node, ast.BoolOp):
            return self._mutate_boolop(node)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self._mutate_not(node)

        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return self._mutate_bool_constant(node)

        return []

    def _mutate_boolop(self, node: ast.BoolOp) -> list[ast.AST]:
        """Mutate a boolean operator (and/or)."""
        mutated = copy.deepcopy(node)
        if isinstance(node.op, ast.And):
            mutated.op = ast.Or()
        else:
            mutated.op = ast.And()
        return [mutated]

    def _mutate_not(self, node: ast.UnaryOp) -> list[ast.AST]:
        """Mutate a not operation by removing the not."""
        return [copy.deepcopy(node.operand)]

    def _mutate_bool_constant(self, node: ast.Constant) -> list[ast.AST]:
        """Mutate a boolean constant (True/False)."""
        mutated = copy.deepcopy(node)
        mutated.value = not node.value
        return [mutated]
