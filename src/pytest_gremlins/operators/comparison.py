"""Comparison mutation operator.

This operator mutates comparison operators (<, <=, >, >=, ==, !=).
"""

from __future__ import annotations

import ast
import copy
from typing import ClassVar


class ComparisonOperator:
    """Mutate comparison operators.

    Generates mutations for comparison operators, swapping them with
    related operators to catch off-by-one and boundary condition bugs.

    Mutations:
        - < -> <=, >
        - <= -> <, >
        - > -> >=, <
        - >= -> >, <
        - == -> !=
        - != -> ==
    """

    MUTATIONS: ClassVar[dict[type[ast.cmpop], list[type[ast.cmpop]]]] = {
        ast.Lt: [ast.LtE, ast.Gt],
        ast.LtE: [ast.Lt, ast.Gt],
        ast.Gt: [ast.GtE, ast.Lt],
        ast.GtE: [ast.Gt, ast.Lt],
        ast.Eq: [ast.NotEq],
        ast.NotEq: [ast.Eq],
    }

    OP_TO_SYMBOL: ClassVar[dict[type[ast.cmpop], str]] = {
        ast.Lt: '<',
        ast.LtE: '<=',
        ast.Gt: '>',
        ast.GtE: '>=',
        ast.Eq: '==',
        ast.NotEq: '!=',
    }

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'comparison'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Swap comparison operators (<, <=, >, >=, ==, !=)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Compare node with supported operators.
        """
        if not isinstance(node, ast.Compare):
            return False

        return any(type(op) in self.MUTATIONS for op in node.ops)

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes, one for each possible mutation.
        """
        if not isinstance(node, ast.Compare):
            return []

        mutations: list[ast.AST] = []

        for i, op in enumerate(node.ops):
            op_type = type(op)
            if op_type in self.MUTATIONS:
                for replacement_op_type in self.MUTATIONS[op_type]:
                    mutated = copy.deepcopy(node)
                    mutated.ops[i] = replacement_op_type()
                    mutations.append(mutated)

        return mutations

    def get_symbol(self, op: ast.cmpop) -> str:
        """Get the symbol for a comparison operator.

        Args:
            op: A comparison operator AST node.

        Returns:
            The symbol string (e.g., '<', '<=', '=='), or '?' if unknown.
        """
        return self.OP_TO_SYMBOL.get(type(op), '?')
