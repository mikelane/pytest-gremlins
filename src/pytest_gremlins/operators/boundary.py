"""Boundary mutation operator.

This operator mutates boundary conditions by shifting integer values by +/- 1.
"""

from __future__ import annotations

import ast
import copy


class BoundaryOperator:
    """Mutate boundary conditions in comparisons.

    Generates mutations for integer constants in comparisons by shifting
    them by +/- 1 to catch off-by-one errors.

    Mutations:
        - x >= 18 -> x >= 17, x >= 19
        - x > 0 -> x > -1, x > 1
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'boundary'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Shift boundary values by +/- 1 in comparisons'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a comparison with an integer constant.
        """
        if not isinstance(node, ast.Compare):
            return False

        if self._has_integer_constant_on_left(node):
            return True

        return self._has_integer_constant_in_comparators(node)

    def _has_integer_constant_on_left(self, node: ast.Compare) -> bool:
        """Check if the left side of the comparison is an integer constant."""
        if isinstance(node.left, ast.Constant):
            return isinstance(node.left.value, int) and not isinstance(node.left.value, bool)
        return False

    def _has_integer_constant_in_comparators(self, node: ast.Compare) -> bool:
        """Check if any comparator is an integer constant."""
        for comp in node.comparators:
            if isinstance(comp, ast.Constant) and isinstance(comp.value, int) and not isinstance(comp.value, bool):
                return True
        return False

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes, one for each boundary shift.
        """
        if not isinstance(node, ast.Compare):
            return []

        mutations: list[ast.AST] = []

        if self._has_integer_constant_on_left(node):
            mutations.extend(self._mutate_left_constant(node))

        if self._has_integer_constant_in_comparators(node):
            mutations.extend(self._mutate_comparator_constants(node))

        return mutations

    def _mutate_left_constant(self, node: ast.Compare) -> list[ast.AST]:
        """Mutate an integer constant on the left side of a comparison."""
        if not isinstance(node.left, ast.Constant):  # pragma: no cover
            return []

        value = node.left.value
        if not isinstance(value, int) or isinstance(value, bool):  # pragma: no cover
            return []

        mutations: list[ast.AST] = []

        for delta in [-1, 1]:
            mutated = copy.deepcopy(node)
            if isinstance(mutated.left, ast.Constant):  # pragma: no branch
                mutated.left.value = value + delta
            mutations.append(mutated)

        return mutations

    def _mutate_comparator_constants(self, node: ast.Compare) -> list[ast.AST]:
        """Mutate integer constants in the comparators."""
        mutations: list[ast.AST] = []

        for i, comp in enumerate(node.comparators):
            if isinstance(comp, ast.Constant) and isinstance(comp.value, int) and not isinstance(comp.value, bool):
                value = comp.value
                for delta in [-1, 1]:
                    mutated = copy.deepcopy(node)
                    mutated_comp = mutated.comparators[i]
                    if isinstance(mutated_comp, ast.Constant):  # pragma: no branch
                        mutated_comp.value = value + delta
                    mutations.append(mutated)

        return mutations
