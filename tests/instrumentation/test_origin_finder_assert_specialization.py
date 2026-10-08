"""An assert holding gremlin switches becomes one plain assert per gremlin so pytest can explain it (#603)."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.origin_finder import _specialize_asserts

_SWITCHED_ASSERT = (
    "def check(n):\n    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0), 'bad'\n    return n\n"
)


def _run_check(source_tree: ast.Module, active: str, value: int) -> int:
    namespace: dict[str, object] = {'__gremlin_active__': active}
    exec(compile(source_tree, '<test>', 'exec'), namespace)  # noqa: S102
    return namespace['check'](value)  # type: ignore[operator, no-any-return]


@pytest.mark.small
class DescribeSpecializeAsserts:
    def it_leaves_no_switch_inside_any_assert(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_ASSERT))

        asserts = [node for node in ast.walk(specialized) if isinstance(node, ast.Assert)]

        assert [ast.unparse(node.test) for node in asserts] == ['n >= 0', 'n > 0']

    def it_runs_the_active_gremlins_assert(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_ASSERT))

        assert _run_check(specialized, 'g001', 0) == 0

    def it_runs_the_original_assert_when_no_gremlin_is_active(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_ASSERT))

        with pytest.raises(AssertionError, match='bad'):
            _run_check(specialized, '', 0)

    def it_keeps_an_assert_without_switches_untouched(self) -> None:
        tree = ast.parse('assert 1 < 2\n')

        assert ast.dump(_specialize_asserts(tree)) == ast.dump(ast.parse('assert 1 < 2\n'))
