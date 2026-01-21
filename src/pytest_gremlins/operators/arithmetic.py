"""Arithmetic mutation operator.

This operator mutates arithmetic operators (+, -, *, /, //, %, **).
"""

from __future__ import annotations

import ast
import copy
from typing import ClassVar


class ArithmeticOperator:
    """Mutate arithmetic operators.

    Generates mutations for arithmetic operators, swapping them with
    related operators to catch calculation errors.

    Mutations:
        - + -> -
        - - -> +
        - * -> /
        - / -> *
        - // -> /
        - % -> //
        - ** -> *
    """

    MUTATIONS: ClassVar[dict[type[ast.operator], list[type[ast.operator]]]] = {
        ast.Add: [ast.Sub],
        ast.Sub: [ast.Add],
        ast.Mult: [ast.Div],
        ast.Div: [ast.Mult],
        ast.FloorDiv: [ast.Div],
        ast.Mod: [ast.FloorDiv],
        ast.Pow: [ast.Mult],
    }

    OP_TO_SYMBOL: ClassVar[dict[type[ast.operator], str]] = {
        ast.Add: '+',
        ast.Sub: '-',
        ast.Mult: '*',
        ast.Div: '/',
        ast.FloorDiv: '//',
        ast.Mod: '%',
        ast.Pow: '**',
    }

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'arithmetic'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Swap arithmetic operators (+, -, *, /, //, %, **)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a BinOp node with a supported arithmetic operator.
        """
        if not isinstance(node, ast.BinOp):
            return False

        return type(node.op) in self.MUTATIONS

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes, one for each possible mutation.
        """
        if not isinstance(node, ast.BinOp):
            return []

        op_type = type(node.op)
        if op_type not in self.MUTATIONS:
            return []

        mutations: list[ast.AST] = []
        for replacement_op_type in self.MUTATIONS[op_type]:
            mutated = copy.deepcopy(node)
            mutated.op = replacement_op_type()
            mutations.append(mutated)

        return mutations

    def get_symbol(self, op: ast.operator) -> str:
        """Get the symbol for an arithmetic operator.

        Args:
            op: An arithmetic operator AST node.

        Returns:
            The symbol string (e.g., '+', '-', '*'), or '?' if unknown.
        """
        return self.OP_TO_SYMBOL.get(type(op), '?')
