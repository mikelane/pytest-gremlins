"""AST transformer for mutation switching.

This module provides the AST transformations needed to embed mutations
into Python source code with environment variable-controlled switching.
"""

from __future__ import annotations

import ast
import copy
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.operators import (
    ArithmeticOperator,
    BooleanOperator,
    BoundaryOperator,
    ComparisonOperator,
    GremlinOperator,
    OperatorRegistry,
    ReturnOperator,
)


_comparison_operator = ComparisonOperator()

COMPARISON_MUTATIONS: dict[type[ast.cmpop], list[type[ast.cmpop]]] = ComparisonOperator.MUTATIONS

OP_TO_SYMBOL: dict[type[ast.cmpop], str] = ComparisonOperator.OP_TO_SYMBOL


def _create_default_registry() -> OperatorRegistry:
    """Create and populate the default operator registry with all 5 operators."""
    registry = OperatorRegistry()
    registry.register(ComparisonOperator)
    registry.register(ArithmeticOperator)
    registry.register(BooleanOperator)
    registry.register(BoundaryOperator)
    registry.register(ReturnOperator)
    return registry


_default_registry = _create_default_registry()


def get_default_registry() -> OperatorRegistry:
    """Get the default operator registry with all 5 operators registered.

    Returns:
        OperatorRegistry with comparison, arithmetic, boolean, boundary, and return operators.
    """
    return _default_registry


def create_gremlins_for_compare(
    node: ast.Compare,
    file_path: str,
    id_generator: Callable[[], str],
) -> list[Gremlin]:
    """Create gremlins for a comparison node.

    This is the shared logic for creating gremlins from comparison AST nodes.
    Used by both GremlinCollector and MutationSwitchingTransformer.

    Args:
        node: The comparison AST node.
        file_path: Path to the source file (for gremlin metadata).
        id_generator: Callable that returns the next gremlin ID.

    Returns:
        List of Gremlin objects for each possible mutation.
    """
    gremlins: list[Gremlin] = []
    mutations = generate_comparison_mutations(node)
    for mutated_node in mutations:
        original_op = _comparison_operator.get_symbol(node.ops[0])
        mutated_op = _comparison_operator.get_symbol(mutated_node.ops[0])
        gremlin = Gremlin(
            gremlin_id=id_generator(),
            file_path=file_path,
            line_number=node.lineno,
            original_node=node,
            mutated_node=mutated_node,
            operator_name='comparison',
            description=f'{original_op} to {mutated_op}',
        )
        gremlins.append(gremlin)
    return gremlins


def generate_comparison_mutations(node: ast.Compare) -> list[ast.Compare]:
    """Generate mutated variants of a comparison node.

    This function delegates to the ComparisonOperator for mutation generation.

    Args:
        node: A comparison AST node (e.g., x < 10).

    Returns:
        List of mutated comparison nodes, one for each possible mutation.
    """
    mutations = _comparison_operator.mutate(node)
    return [m for m in mutations if isinstance(m, ast.Compare)]


def create_gremlins_for_node(
    node: ast.AST,
    operator: GremlinOperator,
    file_path: str,
    id_generator: Callable[[], str],
) -> list[Gremlin]:
    """Create gremlins for any AST node using a specific operator.

    Args:
        node: The AST node to mutate.
        operator: The operator to use for mutation.
        file_path: Path to the source file (for gremlin metadata).
        id_generator: Callable that returns the next gremlin ID.

    Returns:
        List of Gremlin objects for each possible mutation.
    """
    if not operator.can_mutate(node):
        return []

    mutations = operator.mutate(node)
    gremlins: list[Gremlin] = []

    for mutated_node in mutations:
        description = _get_mutation_description(node, mutated_node, operator)
        gremlin = Gremlin(
            gremlin_id=id_generator(),
            file_path=file_path,
            line_number=getattr(node, 'lineno', 0),
            original_node=node,
            mutated_node=mutated_node,
            operator_name=operator.name,
            description=description,
        )
        gremlins.append(gremlin)

    return gremlins


def _get_comparison_description(original: ast.Compare, mutated: ast.Compare) -> str:
    """Get description for comparison mutation."""
    original_op = _comparison_operator.get_symbol(original.ops[0])
    mutated_op = _comparison_operator.get_symbol(mutated.ops[0])
    return f'{original_op} to {mutated_op}'


def _get_arithmetic_description(original: ast.BinOp, mutated: ast.BinOp) -> str:
    """Get description for arithmetic mutation."""
    arithmetic_op = ArithmeticOperator()
    original_sym = arithmetic_op.get_symbol(original.op)
    mutated_sym = arithmetic_op.get_symbol(mutated.op)
    return f'{original_sym} to {mutated_sym}'


def _get_boolean_description(original: ast.AST, mutated: ast.AST) -> str | None:
    """Get description for boolean mutation."""
    if isinstance(original, ast.BoolOp) and isinstance(mutated, ast.BoolOp):
        orig = 'and' if isinstance(original.op, ast.And) else 'or'
        mut = 'and' if isinstance(mutated.op, ast.And) else 'or'
        return f'{orig} to {mut}'
    if isinstance(original, ast.UnaryOp) and isinstance(original.op, ast.Not):
        return 'not x to x'
    if isinstance(original, ast.Constant) and isinstance(mutated, ast.Constant):
        return f'{original.value!r} to {mutated.value!r}'
    return None  # pragma: no cover


def _get_return_description(original: ast.AST, mutated: ast.AST) -> str | None:
    """Get description for return mutation."""
    if isinstance(mutated, ast.Return) and mutated.value is None:
        return 'return value to None'
    if (
        isinstance(original, ast.Return)
        and isinstance(mutated, ast.Return)
        and isinstance(original.value, ast.Constant)
        and isinstance(mutated.value, ast.Constant)
    ):
        return f'return {original.value.value!r} to {mutated.value.value!r}'
    return None  # pragma: no cover


def _get_mutation_description(
    original: ast.AST,
    mutated: ast.AST,
    operator: GremlinOperator,
) -> str:
    """Generate a human-readable description of a mutation.

    Args:
        original: The original AST node.
        mutated: The mutated AST node.
        operator: The operator that created the mutation.

    Returns:
        A description string for the mutation.
    """
    if operator.name == 'comparison' and isinstance(original, ast.Compare) and isinstance(mutated, ast.Compare):
        return _get_comparison_description(original, mutated)

    if operator.name == 'arithmetic' and isinstance(original, ast.BinOp) and isinstance(mutated, ast.BinOp):
        return _get_arithmetic_description(original, mutated)

    if operator.name == 'boolean':
        desc = _get_boolean_description(original, mutated)
        if desc:  # pragma: no branch
            return desc

    if operator.name == 'boundary' and isinstance(original, ast.Compare) and isinstance(mutated, ast.Compare):
        return 'boundary shift +/-1'

    if operator.name == 'return':
        desc = _get_return_description(original, mutated)
        if desc:
            return desc

    return f'{operator.name} mutation'  # pragma: no cover


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
        gremlins = create_gremlins_for_compare(node, self.file_path, self._next_gremlin_id)
        self.gremlins.extend(gremlins)
        self.generic_visit(node)


def collect_gremlins(source: str, file_path: str) -> tuple[list[Gremlin], ast.Module]:
    """Collect gremlins from source code without modifying it.

    This function parses the source and identifies all potential mutation
    points, returning the gremlins found and the original (unmodified) AST.

    Note: This does NOT instrument the code. For instrumentation with
    mutation switching embedded, use transform_source() instead.

    Args:
        source: The Python source code to analyze.
        file_path: The path to the source file (for gremlin metadata).

    Returns:
        Tuple of (list of gremlins, original unmodified AST).
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


def build_switching_statement(
    original: ast.stmt,
    gremlins: list[Gremlin],
) -> ast.If:
    """Build an AST statement that switches between original and mutated statements.

    Creates a nested If statement that checks __gremlin_active__
    and executes the appropriate statement based on which gremlin is active.

    Args:
        original: The original AST statement node.
        gremlins: List of gremlins that apply to this statement.

    Returns:
        An If AST node implementing the switching logic.
    """
    gremlin_active = ast.Name(id='__gremlin_active__', ctx=ast.Load())

    result: ast.stmt = copy.deepcopy(original)

    for gremlin in reversed(gremlins):
        condition = ast.Compare(
            left=gremlin_active,
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=gremlin.gremlin_id)],
        )
        mutated_stmt: ast.stmt = copy.deepcopy(gremlin.mutated_node)  # type: ignore[assignment]
        result = ast.If(
            test=condition,
            body=[mutated_stmt],
            orelse=[result],
        )

    return result  # type: ignore[return-value]


class MutationSwitchingTransformer(ast.NodeTransformer):
    """AST transformer that replaces mutation points with switching expressions.

    This transformer walks the AST and replaces each mutation point (e.g.,
    comparison expression) with a switching expression that selects the
    appropriate mutation based on the __gremlin_active__ variable.
    """

    def __init__(
        self,
        file_path: str,
        operators: list[GremlinOperator] | None = None,
    ) -> None:
        self.file_path = file_path
        self.gremlins: list[Gremlin] = []
        self._gremlin_counter = 0
        self._operators = operators if operators is not None else get_default_registry().get_all()

    def _next_gremlin_id(self) -> str:
        self._gremlin_counter += 1
        return f'g{self._gremlin_counter:03d}'

    def _create_gremlins_for_compare(self, node: ast.Compare) -> list[Gremlin]:
        """Create gremlins for a comparison node."""
        return create_gremlins_for_compare(node, self.file_path, self._next_gremlin_id)

    def _get_operators_for_node(self, node: ast.AST) -> list[GremlinOperator]:
        """Get all operators that can mutate the given node."""
        return [op for op in self._operators if op.can_mutate(node)]

    def _create_gremlins_for_node(self, node: ast.AST) -> list[Gremlin]:
        """Create gremlins for any node using all applicable operators."""
        all_gremlins: list[Gremlin] = []
        for operator in self._get_operators_for_node(node):
            gremlins = create_gremlins_for_node(
                node,
                operator,
                self.file_path,
                self._next_gremlin_id,
            )
            all_gremlins.extend(gremlins)
        return all_gremlins

    def visit_Compare(self, node: ast.Compare) -> ast.expr:
        """Replace comparison nodes with mutation switching expressions."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)

    def visit_BinOp(self, node: ast.BinOp) -> ast.expr:
        """Replace binary operation nodes with mutation switching expressions."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.expr:
        """Replace boolean operation nodes with mutation switching expressions."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.expr:
        """Replace unary operation nodes (including 'not') with mutation switching."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)

    def visit_Constant(self, node: ast.Constant) -> ast.expr:
        """Replace boolean constants with mutation switching expressions."""
        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_expression(node, gremlins)

    def visit_Return(self, node: ast.Return) -> ast.stmt:
        """Replace return statements with mutation switching."""
        self.generic_visit(node)

        gremlins = self._create_gremlins_for_node(node)
        if not gremlins:
            return node

        self.gremlins.extend(gremlins)
        return build_switching_statement(node, gremlins)


def transform_source(
    source: str,
    file_path: str,
    operators: list[GremlinOperator] | None = None,
) -> tuple[list[Gremlin], ast.Module]:
    """Transform source code by embedding mutation switching.

    This is the main entry point for instrumenting Python source code.
    It parses the source, identifies mutation points, and replaces them
    with switching expressions that can toggle between original and
    mutated behavior based on the ACTIVE_GREMLIN environment variable.

    Args:
        source: The Python source code to transform.
        file_path: The path to the source file (for gremlin metadata).
        operators: Optional list of operators to use. If None, uses all 5 default operators.

    Returns:
        Tuple of (list of gremlins, transformed AST with embedded switches).
    """
    tree = ast.parse(source)
    transformer = MutationSwitchingTransformer(file_path, operators=operators)
    new_tree = transformer.visit(tree)
    if not isinstance(new_tree, ast.Module):  # pragma: no cover
        raise TypeError(f'Expected ast.Module, got {type(new_tree).__name__}')
    return transformer.gremlins, new_tree
