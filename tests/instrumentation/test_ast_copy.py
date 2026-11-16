"""Tests that ``copy_ast`` copies AST trees of any depth without recursing (#814)."""

from __future__ import annotations

import ast
import copy
from typing import Any

import pytest

from pytest_gremlins.ast_copy import copy_ast
from pytest_gremlins.instrumentation.transformer import transform_source

# Far deeper than the interpreter's default recursion limit, so any recursive copy would fail.
DEPTH_BEYOND_RECURSION_LIMIT = 5000
# Far more nodes than any tree copied under the cap, so only a copy that never finishes reaches it.
NODE_COPY_CAP = 1000


def _left_leaning_sum(terms: int) -> ast.expr:
    """Build ``x + x + ... + x`` without recursion, the way the parser nests it."""
    chain: ast.expr = ast.Name(id='x', ctx=ast.Load())
    for _ in range(terms - 1):
        chain = ast.BinOp(left=chain, op=ast.Add(), right=ast.Name(id='x', ctx=ast.Load()))
    return chain


@pytest.fixture
def capped_node_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a copy that would never finish instead of hanging; ``copy_ast`` calls ``copy.copy`` once per node."""
    copies_left = NODE_COPY_CAP
    real_copy = copy.copy

    def capped_copy(node: Any) -> Any:
        nonlocal copies_left
        copies_left -= 1
        if copies_left < 0:
            raise AssertionError(f'copy_ast copied more than {NODE_COPY_CAP} nodes of a tree of a few nodes')
        return real_copy(node)

    monkeypatch.setattr(copy, 'copy', capped_copy)


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

    def it_copies_a_node_built_without_one_of_its_fields(self) -> None:
        name_without_a_context = ast.Name(id='x')  # Python 3.11 and 3.12 leave ``ctx`` unset altogether

        copied = copy_ast(name_without_a_context)

        assert copied.id == 'x'

    def it_copies_a_tree_nested_beyond_the_recursion_limit(self) -> None:
        deep = _left_leaning_sum(DEPTH_BEYOND_RECURSION_LIMIT)

        copied = copy_ast(deep)

        assert sum(1 for _ in ast.walk(copied)) == sum(1 for _ in ast.walk(deep))


@pytest.mark.small
class DescribeCopyAstOfLinkedNodes:
    """Libraries such as griffe and executing set ``child.parent = node`` on the trees they parse (#1027)."""

    @pytest.mark.usefixtures('capped_node_copies')
    def it_copies_a_tree_whose_child_links_back_to_its_parent(self) -> None:
        tree = ast.parse('a + b', mode='eval')
        tree.body.parent = tree  # type: ignore[attr-defined]

        copied = copy_ast(tree)

        assert ast.dump(copied) == ast.dump(tree)

    def it_shares_a_node_held_outside_the_node_fields(self) -> None:
        node = ast.parse('a + b', mode='eval').body
        outside = ast.parse('c')
        node.origin = outside  # type: ignore[attr-defined]

        copied = copy_ast(node)

        assert copied.origin is outside  # type: ignore[attr-defined]

    def it_shares_a_list_held_outside_the_node_fields(self) -> None:
        node = ast.parse('a + b', mode='eval').body
        siblings = [ast.parse('c')]
        node.siblings = siblings  # type: ignore[attr-defined]

        copied = copy_ast(node)

        assert copied.siblings is siblings  # type: ignore[attr-defined]

    @pytest.mark.usefixtures('capped_node_copies')
    def it_instruments_a_return_after_the_load_node_every_parse_shares_was_linked_to_a_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        foreign_name = ast.parse('value', mode='eval').body
        monkeypatch.setattr(foreign_name.ctx, 'parent', foreign_name, raising=False)  # type: ignore[attr-defined]

        gremlins, _ = transform_source('def f(x):\n    return x + x\n', 'm.py')

        assert [gremlin.operator_name for gremlin in gremlins] == ['arithmetic', 'return']
