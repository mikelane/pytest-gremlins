"""Return value mutation operator.

This operator mutates return statements by replacing return values.
"""

from __future__ import annotations

import ast
import copy


class ReturnOperator:
    """Mutate return statements.

    Generates mutations for return statements to verify that tests
    actually check return values.

    Mutations:
        - return x -> return None
        - return True -> return False
        - return False -> return True
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'return'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Replace return values with None, empty, or negated'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a return statement with a non-None value.
        """
        if not isinstance(node, ast.Return):
            return False

        if node.value is None:
            return False

        return not (isinstance(node.value, ast.Constant) and node.value.value is None)

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes.
        """
        if not isinstance(node, ast.Return):
            return []

        if node.value is None:
            return []

        if isinstance(node.value, ast.Constant) and node.value.value is None:
            return []

        mutations: list[ast.AST] = []

        mutations.append(self._mutate_to_none(node))

        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
            mutations.append(self._mutate_bool(node))

        return mutations

    def _mutate_to_none(self, node: ast.Return) -> ast.Return:
        """Mutate return to return None."""
        mutated = copy.deepcopy(node)
        mutated.value = None
        return mutated

    def _mutate_bool(self, node: ast.Return) -> ast.Return:
        """Mutate return True/False to the opposite."""
        mutated = copy.deepcopy(node)
        if isinstance(mutated.value, ast.Constant) and isinstance(node.value, ast.Constant):
            mutated.value.value = not node.value.value
        return mutated
