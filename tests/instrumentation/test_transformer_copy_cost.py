"""Tests that instrumentation copy cost and tree independence hold for deep expressions (#640).

After #611 the instrumented tree is quadratic in the length of a chain. The transformer used to deep-copy the
already-instrumented subtree once per nesting level, which made instrumentation time cubic. The copy is skipped
on the one path that provably does not need it; these tests pin both the copy cost and the independence of the
gremlin records from the instrumented tree.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from typing import Any

import pytest

from pytest_gremlins.instrumentation.transformer import (
    build_switching_expression,
    transform_source,
)

# Doubling a chain may at most quintuple the copy work: linear is 2x, the quadratic output is 4x, cubic is 8x.
MAX_DOUBLING_RATIO = 5
DEEP_CHAIN_TERMS = 500


def _chain(terms: int) -> str:
    return 'def f(x):\n    return ' + ' + '.join(['x'] * terms) + '\n'


def _nested_comparison(levels: int) -> str:
    return 'def f(x):\n    y = ' + '(' * levels + 'x' + ''.join(f' < {i})' for i in range(levels)) + '\n    return y\n'


def _count_nodes_copied(monkeypatch: pytest.MonkeyPatch, source: str) -> int:
    """Count the AST nodes ``copy_ast`` copies while instrumenting ``source``; it copies one node per call."""
    nodes_copied = 0
    real_copy = copy.copy

    def counting_copy(node: Any) -> Any:
        nonlocal nodes_copied
        nodes_copied += isinstance(node, ast.AST)
        return real_copy(node)

    with monkeypatch.context() as patch:
        patch.setattr(copy, 'copy', counting_copy)
        transform_source(source, 'm.py')
    return nodes_copied


@pytest.mark.medium
class DescribeInstrumentationCopyCost:
    def it_does_not_more_than_quintuple_the_nodes_copied_when_the_chain_doubles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _count_nodes_copied(monkeypatch, _chain(120)) <= MAX_DOUBLING_RATIO * _count_nodes_copied(
            monkeypatch, _chain(60)
        )


@pytest.mark.medium
class DescribeDeepChains:
    def it_instruments_a_500_term_chain_at_the_default_recursion_limit(self) -> None:
        gremlins, _ = transform_source(_chain(DEEP_CHAIN_TERMS), 'm.py')

        assert len(gremlins) == DEEP_CHAIN_TERMS  # 499 additions and the return


def _construct_sources() -> dict[str, str]:
    return {
        'chain-assignment': 'def f(x):\n    y = ' + ' + '.join(['x'] * 20) + '\n    return y\n',
        'nested-comparison': _nested_comparison(10),
        'boolean-constant': 'def f():\n    flag = True\n    return flag\n',
        'if-condition': 'def f(x):\n    if x < 1 and True:\n        return 1\n    return -x\n',
        'chain-return': _chain(20),
    }


@pytest.mark.small
class DescribeGremlinRecordsAreIndependentOfTheTree:
    @pytest.mark.parametrize('construct', sorted(_construct_sources()))
    def it_shares_no_original_or_mutated_node_with_the_instrumented_tree(self, construct: str) -> None:
        gremlins, tree = transform_source(_construct_sources()[construct], 'm.py')
        tree_node_ids = {id(node) for node in ast.walk(tree)}

        assert len(gremlins) > 0
        assert not [g for g in gremlins if id(g.original_node) in tree_node_ids]
        assert not [g for g in gremlins if id(g.mutated_node) in tree_node_ids]


@pytest.mark.small
class DescribePublicBuilderStillCopies:
    def it_does_not_place_the_input_node_in_the_returned_expression(self) -> None:
        gremlins, _ = transform_source('x = a + b\n', 'm.py')
        original = gremlins[0].original_node
        assert isinstance(original, ast.expr)

        switched = build_switching_expression(original, gremlins)

        assert id(original) not in {id(node) for node in ast.walk(switched)}


# Recorded from main before the change (sha256 of the gremlin ids, operators, lines, descriptions and unparse).
RECORDED_DIGESTS = {
    'chain20': '3e9caf485cc8fcd3795ed1224258936c749216b7f5806b14c9267d57e260ec94',  # pragma: allowlist secret
    'assign_chain': 'eeb0c0439ade27cb92bd726576567abdef2c8fb215e77e5e4439b1c204a8d8a9',  # pragma: allowlist secret
    'nested_cmp': 'af9e6a2c0462f266e258e7cc792970a9d7a0dc5b993db4c4227cd356510539d5',  # pragma: allowlist secret
    'const': 'fb28dc43e9a83efb58a583dcedfb89947e777832533dac4cb4c92a491738b0ea',  # pragma: allowlist secret
    'ifcond': 'da7c8b1c8fa40a0fe6ae3a03d79265bf994401e7e704027c03cfd9f12aa1536d',  # pragma: allowlist secret
    'mixed': 'aed7417134274ced7e7c39cf0d22ed935d548a8e8803587c4d8e05bbe7cc1b7b',  # pragma: allowlist secret
    'unary': '3e0bf2179815027c7e8d0f70cce545f1e03a70701be227e0e17fb3b058dfc259',  # pragma: allowlist secret
}

RECORDED_SOURCES = {
    'chain20': _chain(20),
    'assign_chain': 'def f(x):\n    y = ' + ' + '.join(['x'] * 20) + '\n    return y\n',
    'nested_cmp': _nested_comparison(10),
    'const': 'def f():\n    flag = True\n    return flag\n',
    'ifcond': 'def f(x):\n    if x < 1 and True:\n        return 1\n    return -x\n',
    'mixed': 'def f(a, b):\n    return not (a + b * 2 > 3 and (a - 1 < b or b == 0)) or abs(a) + 1 + 2 - 3\n',
    'unary': 'def f(x):\n    return -(-x) + (not x)\n',
}


@pytest.mark.small
class DescribeInstrumentedOutputIsUnchanged:
    @pytest.mark.parametrize('name', sorted(RECORDED_DIGESTS))
    def it_matches_the_output_recorded_before_the_change(self, name: str) -> None:
        gremlins, tree = transform_source(RECORDED_SOURCES[name], 'm.py')
        record = {
            'g': [[g.gremlin_id, g.operator_name, g.line_number, g.description] for g in gremlins],
            'u': ast.unparse(ast.fix_missing_locations(tree)),
        }

        digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()

        assert digest == RECORDED_DIGESTS[name]
