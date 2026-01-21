"""AST transformer for mutation switching.

This module provides the AST transformations needed to embed mutations
into Python source code with environment variable-controlled switching.
"""

from __future__ import annotations

import ast
import copy

from pytest_gremlins.instrumentation.gremlin import Gremlin


COMPARISON_MUTATIONS: dict[type[ast.cmpop], list[type[ast.cmpop]]] = {
    ast.Lt: [ast.LtE, ast.Gt],
    ast.LtE: [ast.Lt, ast.Gt],
    ast.Gt: [ast.GtE, ast.Lt],
    ast.GtE: [ast.Gt, ast.Lt],
    ast.Eq: [ast.NotEq],
    ast.NotEq: [ast.Eq],
}

OP_TO_SYMBOL: dict[type[ast.cmpop], str] = {
    ast.Lt: '<',
    ast.LtE: '<=',
    ast.Gt: '>',
    ast.GtE: '>=',
    ast.Eq: '==',
    ast.NotEq: '!=',
}


def generate_comparison_mutations(node: ast.Compare) -> list[ast.Compare]:
    """Generate mutated variants of a comparison node.

    Args:
        node: A comparison AST node (e.g., x < 10).

    Returns:
        List of mutated comparison nodes, one for each possible mutation.
    """
    mutations: list[ast.Compare] = []

    for i, op in enumerate(node.ops):
        op_type = type(op)
        if op_type in COMPARISON_MUTATIONS:
            for replacement_op_type in COMPARISON_MUTATIONS[op_type]:
                mutated = copy.deepcopy(node)
                mutated.ops[i] = replacement_op_type()
                mutations.append(mutated)

    return mutations


class GremlinCollector(ast.NodeVisitor):
    """Collects gremlins from comparison nodes in an AST."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.gremlins: list[Gremlin] = []
        self._gremlin_counter = 0

    def _next_gremlin_id(self) -> str:
        self._gremlin_counter += 1
        return f'g{self._gremlin_counter:03d}'

    def visit_Compare(self, node: ast.Compare) -> None:
        """Collect gremlins for comparison nodes."""
        mutations = generate_comparison_mutations(node)
        for mutated_node in mutations:
            original_op = OP_TO_SYMBOL.get(type(node.ops[0]), '?')
            mutated_op = OP_TO_SYMBOL.get(type(mutated_node.ops[0]), '?')
            gremlin = Gremlin(
                gremlin_id=self._next_gremlin_id(),
                file_path=self.file_path,
                line_number=node.lineno,
                original_node=node,
                mutated_node=mutated_node,
                operator_name='comparison',
                description=f'{original_op} to {mutated_op}',
            )
            self.gremlins.append(gremlin)
        self.generic_visit(node)


def instrument_source(source: str, file_path: str) -> tuple[list[Gremlin], ast.Module]:
    """Instrument source code to collect gremlins.

    Args:
        source: The Python source code to instrument.
        file_path: The path to the source file (for gremlin metadata).

    Returns:
        Tuple of (list of gremlins, modified AST).
    """
    tree = ast.parse(source)
    collector = GremlinCollector(file_path)
    collector.visit(tree)
    return collector.gremlins, tree


def build_switching_expression(original: ast.expr, gremlins: list[Gremlin]) -> ast.IfExp:
    """Build an AST expression that switches between original and mutated code.

    Creates a nested IfExp (ternary expression) that checks __gremlin_active__
    and returns the appropriate expression based on which gremlin is active.

    The generated code is equivalent to:
        mutated1 if __gremlin_active__ == 'g001' else (
            mutated2 if __gremlin_active__ == 'g002' else (
                original
            )
        )

    Args:
        original: The original AST expression node.
        gremlins: List of gremlins that apply to this expression.

    Returns:
        An IfExp AST node implementing the switching logic.
    """
    gremlin_active = ast.Name(id='__gremlin_active__', ctx=ast.Load())

    result: ast.expr = copy.deepcopy(original)

    for gremlin in reversed(gremlins):
        condition = ast.Compare(
            left=gremlin_active,
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=gremlin.gremlin_id)],
        )
        # mutated_node is stored as ast.AST but is actually an expr for comparison mutations
        mutated_expr: ast.expr = copy.deepcopy(gremlin.mutated_node)  # type: ignore[assignment]
        result = ast.IfExp(
            test=condition,
            body=mutated_expr,
            orelse=result,
        )

    return result  # type: ignore[return-value]


class MutationSwitchingTransformer(ast.NodeTransformer):
    """AST transformer that replaces mutation points with switching expressions.

    This transformer walks the AST and replaces each mutation point (e.g.,
    comparison expression) with a switching expression that selects the
    appropriate mutation based on the __gremlin_active__ variable.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.gremlins: list[Gremlin] = []
        self._gremlin_counter = 0

    def _next_gremlin_id(self) -> str:
        self._gremlin_counter += 1
        return f'g{self._gremlin_counter:03d}'

    def _create_gremlins_for_compare(self, node: ast.Compare) -> list[Gremlin]:
        """Create gremlins for a comparison node."""
        gremlins: list[Gremlin] = []
        mutations = generate_comparison_mutations(node)
        for mutated_node in mutations:
            original_op = OP_TO_SYMBOL.get(type(node.ops[0]), '?')
            mutated_op = OP_TO_SYMBOL.get(type(mutated_node.ops[0]), '?')
            gremlin = Gremlin(
                gremlin_id=self._next_gremlin_id(),
                file_path=self.file_path,
                line_number=node.lineno,
                original_node=node,
                mutated_node=mutated_node,
                operator_name='comparison',
                description=f'{original_op} to {mutated_op}',
            )
            gremlins.append(gremlin)
        return gremlins

    def visit_Compare(self, node: ast.Compare) -> ast.expr:
        """Replace comparison nodes with mutation switching expressions."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_compare(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)


def transform_source(source: str, file_path: str) -> tuple[list[Gremlin], ast.Module]:
    """Transform source code by embedding mutation switching.

    This is the main entry point for instrumenting Python source code.
    It parses the source, identifies mutation points, and replaces them
    with switching expressions that can toggle between original and
    mutated behavior based on the ACTIVE_GREMLIN environment variable.

    Args:
        source: The Python source code to transform.
        file_path: The path to the source file (for gremlin metadata).

    Returns:
        Tuple of (list of gremlins, transformed AST with embedded switches).
    """
    tree = ast.parse(source)
    transformer = MutationSwitchingTransformer(file_path)
    new_tree = transformer.visit(tree)
    assert isinstance(new_tree, ast.Module)
    return transformer.gremlins, new_tree
