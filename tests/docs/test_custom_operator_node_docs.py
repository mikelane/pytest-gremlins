"""Drift check: the guides describe the nodes a custom operator is offered, including calls (issue #698)."""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

GUIDE_DIR = Path(__file__).resolve().parents[2] / 'docs' / 'guide'


@pytest.mark.medium
class DescribeCustomOperatorNodeDocumentation:
    def it_does_not_tell_users_method_calls_produce_no_gremlins(self) -> None:
        text = (GUIDE_DIR / 'operators.md').read_text()

        assert 'produces no gremlins today' not in text

    def it_lists_calls_among_the_nodes_offered_in_the_operators_guide(self) -> None:
        text = (GUIDE_DIR / 'operators.md').read_text()
        paragraph = text[text.index('A custom operator is offered') :]
        first_sentence = paragraph[: paragraph.index('. ')]

        assert re.search(r'\bcalls\b', first_sentence) is not None

    def it_lists_calls_among_the_nodes_offered_in_the_keep_can_mutate_fast_section(self) -> None:
        text = (GUIDE_DIR / 'extensibility.md').read_text()
        section = text[text.index('### Keep can_mutate() Fast') : text.index('### Always Deep Copy')]

        assert re.search(r'\(every comparison, operation, literal and\s+`return`\)', section) is None
        assert re.search(r'\bcalls?\b', section.split('```')[0]) is not None


def _django_operator_example() -> type:
    text = (GUIDE_DIR / 'extensibility.md').read_text()
    section = text[text.index('## Complete Example: Django QuerySet Operator') :]
    source = section.split('```python\n', 1)[1].split('\n```', 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(source, 'extensibility.md', 'exec'), namespace)  # noqa: S102
    operator_class = namespace['DjangoQuerySetOperator']
    assert isinstance(operator_class, type)
    return operator_class


PROMISE_BULLET = re.compile(r'^\s+- (?P<line>.+)$', flags=re.MULTILINE)
PROMISE_SHAPE = re.compile(r'^(?P<source>\w+)\(\) -> (?P<target>\w+)\(\)$')


def _promised_swaps(docstring: str) -> list[tuple[str, str]]:
    swaps = []
    for bullet in PROMISE_BULLET.finditer(docstring):
        shape = PROMISE_SHAPE.match(bullet.group('line'))
        assert shape is not None, f'unparseable promise: {bullet.group("line")!r}'
        swaps.append((shape.group('source'), shape.group('target')))
    return swaps


def _produced_target(operator_class: type, source: str) -> str:
    call = ast.parse(f'queryset.{source}()', mode='eval').body
    operator = operator_class()
    assert operator.can_mutate(call) is True, source
    mutants = operator.mutate(call)
    assert mutants, source
    target = mutants[0].func.attr
    assert isinstance(target, str), source
    return target


def _swaps_not_produced(operator_class: type, promised: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(source, target) for source, target in promised if _produced_target(operator_class, source) != target]


@pytest.mark.medium
class DescribeDjangoOperatorDocExample:
    def it_docs_django_operator_produces_the_mutations_its_docstring_promises(self) -> None:
        operator_class = _django_operator_example()
        promised = _promised_swaps(operator_class.__doc__ or '')
        assert promised

        assert _swaps_not_produced(operator_class, promised) == []

    def it_rejects_a_promise_whose_target_the_code_does_not_produce(self) -> None:
        operator_class = _django_operator_example()
        wrong = _promised_swaps('    - filter() -> first()')

        assert _swaps_not_produced(operator_class, wrong) == [('filter', 'first')]

    def it_rejects_a_promise_written_in_a_shape_it_cannot_parse(self) -> None:
        with pytest.raises(AssertionError, match='unparseable promise'):
            _promised_swaps('    - `exists()` -> (removed)')
