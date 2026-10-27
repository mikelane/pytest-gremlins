"""Custom operators are offered ast.Call nodes (issue #698)."""

from __future__ import annotations

import ast
import copy

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source


class _FilterToExcludeOperator:
    name = 'call_swap'
    description = 'Swap .filter() for .exclude()'

    def can_mutate(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'filter'

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        mutated = copy.deepcopy(node)
        assert isinstance(mutated, ast.Call)
        assert isinstance(mutated.func, ast.Attribute)
        mutated.func.attr = 'exclude'
        return [mutated]

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:  # noqa: ARG002
        return 'filter -> exclude'


@pytest.mark.small
class DescribeCustomOperatorOnCallNodes:
    def it_produces_a_gremlin_for_a_matching_call(self) -> None:
        source = 'def f(qs):\n    return qs.filter(a=1)\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])

        assert [g.operator_name for g in gremlins] == ['call_swap']

    def it_produces_one_gremlin_per_matching_call(self) -> None:
        source = 'def f(qs):\n    a = qs.filter(a=1)\n    return qs.filter(b=2), a, qs.all()\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])

        assert len(gremlins) == 2

    def it_finds_matching_calls_nested_inside_other_calls(self) -> None:
        source = 'def f(qs):\n    return list(qs.filter(a=1))\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])

        assert len(gremlins) == 1

    def it_switches_the_call_when_the_gremlin_is_active(self) -> None:
        source = 'def f(qs):\n    return qs.filter(a=1)\n'
        gremlins, tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])
        ast.fix_missing_locations(tree)

        class _Qs:
            def filter(self, **_kw: int) -> str:
                return 'filter'

            def exclude(self, **_kw: int) -> str:
                return 'exclude'

        results = []
        for active in (None, gremlins[0].gremlin_id):
            namespace: dict[str, object] = {'__gremlin_active__': active}
            exec(compile(tree, 'm.py', 'exec'), namespace)  # noqa: S102
            results.append(namespace['f'](_Qs()))  # type: ignore[operator]

        assert results == ['filter', 'exclude']


class _CountingFilterOperator(_FilterToExcludeOperator):
    def __init__(self) -> None:
        self.call_node_checks = 0

    def can_mutate(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            self.call_node_checks += 1
        return super().can_mutate(node)


@pytest.mark.small
class DescribeCanMutateCostOnCallNodes:
    def it_asks_can_mutate_at_most_twice_per_matching_call(self) -> None:
        operator = _CountingFilterOperator()

        transform_source('def f(qs):\n    return qs.filter(a=1)\n', 'm.py', operators=[operator])

        assert operator.call_node_checks <= 2
