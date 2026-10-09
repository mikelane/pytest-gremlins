"""Tests that chained operations instrument to a polynomial-size AST (#611).

A chain such as ``x + x + ... + x`` used to double the instrumented tree with every extra term, because
each mutated branch copied the already-instrumented left operand. Mutated branches are built from the
un-instrumented operands now: only one gremlin is active at a time, so they never need nested switches.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from functools import reduce
from itertools import (
    cycle,
    islice,
)
from pathlib import Path
import time
from typing import Any

import pytest

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.plugin import _write_instrumented_sources


def _chained_operation_source(operator: str, terms: int, operand: str = 'x') -> str:
    return f'def f(x):\n    return {f" {operator} ".join([operand] * terms)}\n'


def _alternating_boolops(levels: int) -> str:
    """Left-nested ``(((x and x) or x) and x) ...``: each level is its own BoolOp."""
    expression = reduce(lambda inner, op: f'({inner} {op} x)', islice(cycle(('and', 'or')), levels), 'x')
    return f'def f(x):\n    return {expression}\n'


def _node_count(source: str) -> int:
    _, tree = transform_source(source, 'm.py')
    return sum(1 for _ in ast.walk(tree))


def _gremlin_metadata(source: str) -> list[tuple[str, str, int, int, str]]:
    gremlins, _ = transform_source(source, 'm.py')
    return [(g.gremlin_id, g.operator_name, g.line_number, g.original_node.col_offset, g.description) for g in gremlins]


def _call_with_active_gremlin(source: str, active_gremlin_id: str, *args: Any) -> Any:
    _, tree = transform_source(source, 'm.py')
    namespace: dict[str, Any] = {'__gremlin_active__': active_gremlin_id}
    exec(compile(ast.fix_missing_locations(tree), 'm.py', 'exec'), namespace)  # noqa: S102
    return namespace['f'](*args)


@pytest.mark.small
class DescribeGremlinMetadataIsUnchanged:
    """The ids, operators, lines and columns match what main produced before the fix."""

    def it_keeps_every_gremlin_of_a_twelve_term_sum(self) -> None:
        expected = [
            ('m_f6f7_g001', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g002', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g003', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g004', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g005', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g006', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g007', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g008', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g009', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g010', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g011', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g012', 'return', 2, 4, 'return value to None'),
        ]

        assert _gremlin_metadata(_chained_operation_source('+', 12)) == expected

    def it_keeps_every_gremlin_of_a_mixed_chain(self) -> None:
        source = 'def f(a, b, c, d):\n    return a + b * c - d\n'

        assert _gremlin_metadata(source) == [
            ('m_f6f7_g001', 'arithmetic', 2, 15, '* to /'),
            ('m_f6f7_g002', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g003', 'arithmetic', 2, 11, '- to +'),
            ('m_f6f7_g004', 'return', 2, 4, 'return value to None'),
        ]

    def it_keeps_every_gremlin_of_a_right_nested_chain(self) -> None:
        source = 'def f(a, b, c, d):\n    return a + (b + (c + d))\n'

        assert _gremlin_metadata(source) == [
            ('m_f6f7_g001', 'arithmetic', 2, 21, '+ to -'),
            ('m_f6f7_g002', 'arithmetic', 2, 16, '+ to -'),
            ('m_f6f7_g003', 'arithmetic', 2, 11, '+ to -'),
            ('m_f6f7_g004', 'return', 2, 4, 'return value to None'),
        ]

    def it_produces_one_gremlin_per_term_of_a_thirty_term_sum(self) -> None:
        gremlins, _ = transform_source(_chained_operation_source('+', 30), 'm.py')

        assert len(gremlins) == 30


@pytest.mark.medium
class DescribeInstrumentedTreeGrowth:
    """The instrumented tree grows at most quadratically with the chain length."""

    @pytest.mark.parametrize(
        'source_for',
        [
            pytest.param(lambda n: _chained_operation_source('+', n), id='binop'),
            pytest.param(lambda n: _chained_operation_source('and', n), id='boolop'),
            pytest.param(lambda n: 'def f(x):\n    return ' + 'not ' * n + 'x\n', id='unary-not'),
            pytest.param(lambda n: 'def f(x):\n    return ' + '(' * n + 'x' + ' < 1)' * n + '\n', id='nested-compare'),
            pytest.param(lambda n: _chained_operation_source('and', n, operand='(x or x)'), id='nested-boolop'),
        ],
    )
    @pytest.mark.parametrize(('short_length', 'long_length'), [(5, 10), (20, 40)])
    def it_grows_by_at_most_five_times_when_the_chain_doubles(
        self, source_for: Callable[[int], str], short_length: int, long_length: int
    ) -> None:
        growth_ratio = _node_count(source_for(long_length)) / _node_count(source_for(short_length))

        assert growth_ratio <= 5

    def it_grows_by_at_most_five_times_for_nested_alternating_boolops_when_the_depth_doubles(self) -> None:
        growth_ratio = _node_count(_alternating_boolops(10)) / _node_count(_alternating_boolops(5))

        assert growth_ratio <= 5


@pytest.mark.small
class DescribeThirtyTermSumInstrumentsQuickly:
    """Instrumenting a thirty-term sum stays well under a second."""

    def it_instruments_a_thirty_term_sum_in_under_a_second(self) -> None:
        started = time.perf_counter()
        transform_source(_chained_operation_source('+', 30), 'm.py')

        assert time.perf_counter() - started < 1


@pytest.mark.small
class DescribeVerdictsAreUnchanged:
    """Activating one gremlin gives the hand-mutated result; activating none gives the original."""

    def it_returns_the_original_result_when_no_gremlin_is_active(self) -> None:
        assert _call_with_active_gremlin(_chained_operation_source('+', 12), '', 1) == 12

    @pytest.mark.parametrize(
        ('gremlin_number', 'hand_mutated'),
        [
            (1, 'a - b + c + d + e'),
            (2, 'a + b - c + d + e'),
            (3, 'a + b + c - d + e'),
            (4, 'a + b + c + d - e'),
        ],
    )
    def it_matches_the_hand_mutated_source_for_a_sum(self, gremlin_number: int, hand_mutated: str) -> None:
        source = 'def f(a, b, c, d, e):\n    return a + b + c + d + e\n'
        argument_values = {'a': 1, 'b': 20, 'c': 300, 'd': 4000, 'e': 50000}

        actual = _call_with_active_gremlin(source, f'm_f6f7_g{gremlin_number:03d}', *argument_values.values())

        assert actual == eval(hand_mutated, {}, argument_values)  # noqa: S307

    def it_returns_none_when_the_return_gremlin_is_active(self) -> None:
        source = 'def f(a, b, c, d, e):\n    return a + b + c + d + e\n'

        assert _call_with_active_gremlin(source, 'm_f6f7_g005', 1, 20, 300, 4000, 50000) is None

    @pytest.mark.parametrize(
        ('gremlin_number', 'hand_mutated'),
        [
            (1, 'a + b / c - d'),
            (2, 'a - b * c - d'),
            (3, 'a + b * c + d'),
        ],
    )
    def it_matches_the_hand_mutated_source_for_a_mixed_chain(self, gremlin_number: int, hand_mutated: str) -> None:
        source = 'def f(a, b, c, d):\n    return a + b * c - d\n'
        argument_values = {'a': 2, 'b': 3, 'c': 4, 'd': 5}

        actual = _call_with_active_gremlin(source, f'm_f6f7_g{gremlin_number:03d}', *argument_values.values())

        assert actual == eval(hand_mutated, {}, argument_values)  # noqa: S307

    def it_skips_a_pardoned_gremlin_in_the_middle_of_a_chain(self) -> None:
        source = (
            'def f(a, b, c):\n'
            '    return (a +\n'
            '            (b + c))  # gremlin: pardon[equivalent] addition order is not observable here\n'
        )

        gremlins, _ = transform_source(source, 'm.py')

        assert [g.pardoned for g in gremlins] == [True, False, False]


@pytest.mark.small
class DescribeOperandsKeepTheirOwnSwitches:
    """A gremlin on an outer operation leaves the constructs inside its operands as they were written."""

    @pytest.mark.parametrize(
        ('body', 'gremlin_number', 'expected'),
        [
            pytest.param('(lambda y: y + 1)(x) * 2', 1, 4, id='lambda-inner-gremlin'),
            pytest.param('(lambda y: y + 1)(x) * 2', 2, 2.0, id='lambda-outer-gremlin'),
            pytest.param('(n := x + 1) * n', 1, 4, id='walrus-inner-gremlin'),
            pytest.param('(n := x + 1) * n', 2, 1.0, id='walrus-outer-gremlin'),
            pytest.param(
                '[y + 1 for y in range(x)] + [True and x > 1]', 2, [1, 2, 3, False], id='constant-true-to-false'
            ),
            pytest.param('[y + 1 for y in range(x)] + [True and x > 1]', 7, [1, 2, 3, True], id='boolop-and-to-or'),
        ],
    )
    def it_matches_the_hand_mutated_result(self, body: str, gremlin_number: int, expected: Any) -> None:
        source = f'def f(x):\n    return {body}\n'

        assert _call_with_active_gremlin(source, f'm_f6f7_g{gremlin_number:03d}', 3) == expected


@pytest.mark.small
class DescribeNestedGremlinsUnderEverySwitchedConstruct:
    """With x = 3, a gremlin inside an operand and the gremlin on the enclosing construct each take effect."""

    @pytest.mark.parametrize(
        ('body', 'gremlin_number', 'hand_mutated'),
        [
            pytest.param('x + 1 < 4', 1, 'x - 1 < 4', id='compare-inner-add-to-sub'),
            pytest.param('x + 1 < 4', 2, 'x + 1 <= 4', id='compare-outer-lt-to-lte'),
            pytest.param('not (x + 1 > 3)', 1, 'not (x - 1 > 3)', id='unary-not-inner-add-to-sub'),
            pytest.param('not (x + 1 > 3)', 6, '(x + 1 > 3)', id='unary-not-outer-not-x-to-x'),
            pytest.param('-(x + 1)', 1, '-(x - 1)', id='unary-minus-inner-add-to-sub'),
            pytest.param('(x > 3 or x < 0) and x', 1, '(x >= 3 or x < 0) and x', id='boolop-inner-gt-to-gte'),
            pytest.param('(x > 3 or x < 0) and x', 10, '(x > 3 or x < 0) or x', id='boolop-outer-and-to-or'),
        ],
    )
    def it_matches_the_hand_mutated_source(self, body: str, gremlin_number: int, hand_mutated: str) -> None:
        source = f'def f(x):\n    return {body}\n'

        actual = _call_with_active_gremlin(source, f'm_f6f7_g{gremlin_number:03d}', 3)

        assert actual == eval(hand_mutated, {}, {'x': 3})  # noqa: S307


@pytest.mark.medium
class DescribeInstrumentAndWritePath:
    """Instrumenting and writing a long chain stays fast and the written sources stay small."""

    def it_instruments_and_writes_a_twenty_term_sum_well_under_a_second(self, tmp_path: Path) -> None:
        module_path = tmp_path / 'mymod.py'
        source = _chained_operation_source('+', 20)
        module_path.write_text(source)

        started = time.perf_counter()
        _, tree = transform_source(source, str(module_path))
        instrumented_sources_dir = _write_instrumented_sources({str(module_path): tree}, tmp_path)
        elapsed = time.perf_counter() - started

        assert elapsed < 1
        assert (instrumented_sources_dir / 'sources.json').stat().st_size < 1_000_000
