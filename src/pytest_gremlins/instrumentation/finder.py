"""Mutation point finder.

This module provides functionality to find mutation points (nodes that can be
mutated) in an AST.
"""

from __future__ import annotations

import ast


class MutationPointVisitor(ast.NodeVisitor):
    """AST visitor that collects nodes that can be mutated."""

    def __init__(self) -> None:
        self.mutation_points: list[ast.AST] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        """Collect comparison nodes as mutation points."""
        self.mutation_points.append(node)
        self.generic_visit(node)


def find_mutation_points(tree: ast.AST) -> list[ast.AST]:
    """Find all mutation points in an AST.

    Args:
        tree: The AST to search for mutation points.

    Returns:
        List of AST nodes that can be mutated.
    """
    visitor = MutationPointVisitor()
    visitor.visit(tree)
    return visitor.mutation_points
