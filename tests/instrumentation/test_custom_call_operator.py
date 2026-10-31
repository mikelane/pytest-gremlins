"""Custom operators are offered ast.Call nodes (issue #698)."""

from __future__ import annotations

import ast
import copy
from typing import (
    TYPE_CHECKING,
    ClassVar,
    cast,
)

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from collections.abc import Callable


class _FilterMutationOperator:
    """Swaps .filter() for .exclude() and defines no ``get_description``."""

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


class _FilterToExcludeOperator(_FilterMutationOperator):
    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:  # noqa: ARG002
        return 'filter -> exclude'


_FILTER_SOURCE = 'def f(qs):\n    return qs.filter(a=1)\n'


class _QuerySet:
    def filter(self, **_kw: int) -> str:
        return 'filter'

    def exclude(self, **_kw: int) -> str:
        return 'exclude'


def _run_f(tree: ast.Module, active: str | None) -> object:
    ast.fix_missing_locations(tree)
    namespace: dict[str, object] = {'__gremlin_active__': active}
    exec(compile(tree, 'm.py', 'exec'), namespace)  # noqa: S102
    run_f = cast('Callable[[_QuerySet], object]', namespace['f'])
    return run_f(_QuerySet())


@pytest.mark.small
class DescribeCustomOperatorOnCallNodes:
    def it_produces_a_gremlin_for_a_matching_call(self) -> None:
        gremlins, _tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[_FilterToExcludeOperator()])

        assert [g.operator_name for g in gremlins] == ['call_swap']

    def it_produces_one_gremlin_per_matching_call(self) -> None:
        source = 'def f(qs):\n    a = qs.filter(a=1)\n    return qs.filter(b=2), a, qs.all()\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])

        assert [g.operator_name for g in gremlins] == ['call_swap', 'call_swap']

    def it_finds_matching_calls_nested_inside_other_calls(self) -> None:
        source = 'def f(qs):\n    return list(qs.filter(a=1))\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterToExcludeOperator()])

        assert [g.operator_name for g in gremlins] == ['call_swap']

    def it_calls_the_original_method_when_no_gremlin_is_active(self) -> None:
        _gremlins, tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[_FilterToExcludeOperator()])

        assert _run_f(tree, active=None) == 'filter'

    def it_calls_the_mutated_method_when_the_gremlin_is_active(self) -> None:
        gremlins, tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[_FilterToExcludeOperator()])

        assert _run_f(tree, active=gremlins[0].gremlin_id) == 'exclude'


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


def _describe_method_swap(original: ast.AST, mutated: ast.AST) -> str:
    assert isinstance(original, ast.Call)
    assert isinstance(original.func, ast.Attribute)
    assert isinstance(mutated, ast.Call)
    assert isinstance(mutated.func, ast.Attribute)
    return f'{original.func.attr} -> {mutated.func.attr}'


class _FilterAndFirstOperator:
    name = 'call_swap'
    description = 'Swap .filter() for .exclude() and .first() for .last()'
    _SWAPS: ClassVar[dict[str, str]] = {'filter': 'exclude', 'first': 'last'}

    def can_mutate(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in self._SWAPS

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        mutated = copy.deepcopy(node)
        assert isinstance(mutated, ast.Call)
        assert isinstance(mutated.func, ast.Attribute)
        mutated.func.attr = self._SWAPS[mutated.func.attr]
        return [mutated]

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:
        return _describe_method_swap(original, mutated)


class _NonCallableDescriptionOperator(_FilterMutationOperator):
    get_description = None


class _ReturnNoneOperator:
    """Replaces a returned expression with None and describes it by unparsing the nodes it is given."""

    name = 'return_none_custom'
    description = 'Replace a returned expression with None'

    def can_mutate(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Return) and node.value is not None

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        mutated = copy.deepcopy(node)
        assert isinstance(mutated, ast.Return)
        mutated.value = ast.Constant(value=None)
        return [mutated]

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:
        return f'{ast.unparse(original)} -> {ast.unparse(mutated)}'


class _NoArgumentDescriptionOperator(_FilterMutationOperator):
    """Written before ``get_description`` was called, with a helper that takes no arguments."""

    name = 'legacy_filter'

    def get_description(self) -> str:  # type: ignore[override]
        return self.description


class _RaisingDescriptionOperator(_FilterMutationOperator):
    name = 'raising_desc'

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:  # noqa: ARG002
        msg = 'boom'
        raise RuntimeError(msg)


class _NoneDescriptionOperator(_FilterMutationOperator):
    name = 'none_desc'

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str | None:  # type: ignore[override]  # noqa: ARG002
        return None


class _EmptyDescriptionOperator(_FilterMutationOperator):
    name = 'empty_desc'

    def get_description(self, original: ast.AST, mutated: ast.AST) -> str:  # noqa: ARG002
        return ''


@pytest.mark.small
class DescribeCustomOperatorDescriptions:
    def it_uses_the_operator_get_description_for_the_gremlin(self) -> None:
        gremlins, _tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[_FilterToExcludeOperator()])

        assert [g.description for g in gremlins] == ['filter -> exclude']

    @pytest.mark.parametrize(
        'operator',
        [
            pytest.param(_FilterMutationOperator(), id='no-get-description-attribute'),
            pytest.param(_NonCallableDescriptionOperator(), id='non-callable-get-description'),
        ],
    )
    def it_falls_back_to_the_operator_name_when_get_description_is_missing_or_not_callable(
        self, operator: _FilterMutationOperator
    ) -> None:
        gremlins, _tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[operator])

        assert [g.description for g in gremlins] == ['call_swap mutation']

    def it_describes_each_gremlin_on_one_call_chain_by_its_own_swap(self) -> None:
        source = 'def f(qs):\n    return qs.filter(a=1).first()\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[_FilterAndFirstOperator()])

        assert sorted(g.description for g in gremlins) == ['filter -> exclude', 'first -> last']

    def it_describes_a_custom_return_gremlin_from_the_source_as_written(self) -> None:
        source = 'def f(a, b):\n    return a < b\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[ComparisonOperator(), _ReturnNoneOperator()])

        custom = [g for g in gremlins if g.operator_name == 'return_none_custom']
        assert [g.description for g in custom] == ['return a < b -> return None']

    @pytest.mark.parametrize(
        'operator',
        [
            pytest.param(_NoArgumentDescriptionOperator(), id='takes-no-arguments'),
            pytest.param(_RaisingDescriptionOperator(), id='raises'),
        ],
    )
    def it_keeps_the_files_other_gremlins_when_a_legacy_get_description_takes_no_arguments(
        self, operator: _FilterMutationOperator
    ) -> None:
        source = 'def f(qs, a, b):\n    return qs.filter(x=a < b)\n'

        gremlins, _tree = transform_source(source, 'm.py', operators=[ComparisonOperator(), operator])

        assert {g.operator_name for g in gremlins} == {'comparison', operator.name}
        assert [g.description for g in gremlins if g.operator_name == operator.name] == [f'{operator.name} mutation']

    @pytest.mark.parametrize(
        'operator',
        [
            pytest.param(_NoneDescriptionOperator(), id='none'),
            pytest.param(_EmptyDescriptionOperator(), id='empty'),
        ],
    )
    def it_falls_back_to_the_operator_name_when_get_description_returns_none(
        self, operator: _FilterMutationOperator
    ) -> None:
        gremlins, _tree = transform_source(_FILTER_SOURCE, 'm.py', operators=[operator])

        assert [g.description for g in gremlins] == [f'{operator.name} mutation']
