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
