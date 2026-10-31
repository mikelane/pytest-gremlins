"""Copy AST trees of any depth without recursing."""

from __future__ import annotations

import ast
import copy
from typing import TypeVar

NodeT = TypeVar('NodeT', bound=ast.AST)


def copy_ast(root: NodeT) -> NodeT:
    """Return an independent copy of ``root`` and every node below it.

    ``copy.deepcopy`` recurses several frames per level, so a chain such as ``x + x + ... + x`` of a few hundred
    terms exhausts the interpreter's recursion limit. This walks the tree with an explicit stack instead.

    Args:
        root: The node whose subtree to copy.

    Returns:
        A copy of ``root`` of the same type. Every AST node and list field in it is new; leaf values such as
        names and constants are shared, as they are immutable.

    Examples:
        >>> tree = ast.parse('a + b + c', mode='eval')
        >>> clone = copy_ast(tree)
        >>> clone is tree, clone.body is tree.body, clone.body.left is tree.body.left
        (False, False, False)
        >>> ast.dump(clone) == ast.dump(tree)
        True
    """
    root_copy = copy.copy(root)
    pending: list[ast.AST] = [root_copy]
    while pending:
        node = pending.pop()
        for field, value in vars(node).items():
            if isinstance(value, ast.AST):
                child = copy.copy(value)
                setattr(node, field, child)
                pending.append(child)
            elif isinstance(value, list):
                children = [copy.copy(item) if isinstance(item, ast.AST) else item for item in value]
                setattr(node, field, children)
                pending.extend(item for item in children if isinstance(item, ast.AST))
    return root_copy
