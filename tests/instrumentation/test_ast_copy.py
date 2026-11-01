"""Tests that ``copy_ast`` copies AST trees of any depth without recursing (#814)."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.ast_copy import copy_ast

# Far deeper than the interpreter's default recursion limit, so any recursive copy would fail.
DEPTH_BEYOND_RECURSION_LIMIT = 5000


def _left_leaning_sum(terms: int) -> ast.expr:
    """Build ``x + x + ... + x`` without recursion, the way the parser nests it."""
    chain: ast.expr = ast.Name(id='x', ctx=ast.Load())
    for _ in range(terms - 1):
        chain = ast.BinOp(left=chain, op=ast.Add(), right=ast.Name(id='x', ctx=ast.Load()))
    return chain


@pytest.mark.small
class DescribeCopyAst:
    @pytest.mark.parametrize(
        'source',
        [
            'x = a + b * 2\n',
            'def f(a, *args, k=1, **kw):\n    return [i for i in args if i > a] or {k: kw}\n',
            "print(f'{a!r:>{width}}', b'bytes', 1.5j, ..., None)\n",
            'async def g(x):\n    async with x as y:\n        await y\n',
        ],
    )
    def it_returns_a_tree_equal_to_the_original(self, source: str) -> None:
        tree = ast.parse(source)

        copied = copy_ast(tree)

        assert ast.dump(copied, include_attributes=True) == ast.dump(tree, include_attributes=True)

    def it_shares_no_node_with_the_original(self) -> None:
        tree = ast.parse('x = a + b * 2\nfor i in range(3):\n    print(i)\n')

        copied = copy_ast(tree)

        assert {id(n) for n in ast.walk(copied)}.isdisjoint({id(n) for n in ast.walk(tree)})

    def it_does_not_let_edits_to_the_copy_reach_the_original(self) -> None:
        tree = ast.parse('x = a + b\n')
        original_dump = ast.dump(tree)

        copied = copy_ast(tree)
        copied.body.append(ast.Pass())
        copied.body[0].value.op = ast.Sub()  # type: ignore[attr-defined]

        assert ast.dump(tree) == original_dump

    def it_keeps_attributes_set_outside_the_node_fields(self) -> None:
        node = ast.parse('a + b', mode='eval').body
        node.pardoned = True  # type: ignore[attr-defined]

        copied = copy_ast(node)

        assert copied.pardoned is True  # type: ignore[attr-defined]

    def it_copies_a_tree_nested_beyond_the_recursion_limit(self) -> None:
        deep = _left_leaning_sum(DEPTH_BEYOND_RECURSION_LIMIT)

        copied = copy_ast(deep)

        assert sum(1 for _ in ast.walk(copied)) == sum(1 for _ in ast.walk(deep))
