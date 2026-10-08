"""An assert holding gremlin switches becomes one plain assert per gremlin so pytest can explain it (#603)."""

from __future__ import annotations

import ast
import importlib.machinery
from pathlib import Path
from types import ModuleType

from _pytest.assertion.rewrite import AssertionRewritingHook
import pytest

from pytest_gremlins.instrumentation.origin_finder import (
    GremlinLoader,
    _specialize_asserts,
)

_SWITCHED_ASSERT = (
    "def check(n):\n    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0), 'bad'\n    return n\n"
)


def _run_check(source_tree: ast.Module, active: str, value: int) -> int:
    namespace: dict[str, object] = {'__gremlin_active__': active}
    exec(compile(source_tree, '<test>', 'exec'), namespace)  # noqa: S102
    return namespace['check'](value)  # type: ignore[operator, no-any-return]


_DEEP_ELIF_BRANCHES = 600


def _deep_elif_with_switched_assert_at_the_bottom() -> ast.Module:
    branches = ''.join(f'    elif flags[{index}]:\n        return {index}\n' for index in range(1, _DEEP_ELIF_BRANCHES))
    bottom = "    else:\n        assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
    return ast.parse(f'def check(flags, n):\n    if flags[0]:\n        return 0\n{branches}{bottom}')


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

    def it_specializes_an_assert_at_the_bottom_of_a_very_deep_elif_chain(self) -> None:
        specialized = _specialize_asserts(_deep_elif_with_switched_assert_at_the_bottom())

        asserts = [node for node in ast.walk(specialized) if isinstance(node, ast.Assert)]

        assert [ast.unparse(node.test) for node in asserts] == ['n >= 0', 'n > 0']

    def it_leaves_an_assert_unspecialized_when_specializing_it_overflows_the_stack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def overflow(_node: ast.Assert, _active_id: str | None) -> ast.Assert:
            raise RecursionError

        monkeypatch.setattr('pytest_gremlins.instrumentation.origin_finder._resolve_assert', overflow)
        tree = ast.parse(_SWITCHED_ASSERT)
        before = ast.dump(tree)

        assert ast.dump(_specialize_asserts(tree)) == before


_TWO_SWITCHES_ASSERT = (
    'def check(n):\n'
    "    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0) and "
    "(n < 9 if __gremlin_active__ == 'g002' else n < 10)\n"
    '    return n\n'
)

_SWITCHED_MESSAGE_ASSERT = "def check(n):\n    assert n > 0, ('low' if __gremlin_active__ == 'g001' else 'bad')\n"

_SWITCHED_ASSERT_IN_HANDLER = (
    'def check(n):\n'
    '    try:\n'
    '        pass\n'
    '    except ValueError:\n'
    "        assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
)

_SWITCHED_ASSERT_IN_MATCH_CASE = (
    'def check(n):\n'
    '    match n:\n'
    '        case _:\n'
    "            assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
)


def _assert_conditions(tree: ast.Module) -> list[str]:
    return [ast.unparse(node.test) for node in ast.walk(tree) if isinstance(node, ast.Assert)]


@pytest.mark.small
class DescribeSpecializeAssertsSwitchShapes:
    """Every gremlin switch an assert holds is resolved, and nothing that merely looks like one is touched."""

    def it_writes_one_assert_per_gremlin_and_one_for_the_original(self) -> None:
        specialized = _specialize_asserts(ast.parse(_TWO_SWITCHES_ASSERT))

        assert _assert_conditions(specialized) == ['n >= 0 and n < 10', 'n > 0 and n < 9', 'n > 0 and n < 10']

    def it_runs_the_first_gremlins_assert_when_it_is_active(self) -> None:
        specialized = _specialize_asserts(ast.parse(_TWO_SWITCHES_ASSERT))

        assert _run_check(specialized, 'g001', 0) == 0

    def it_runs_the_second_gremlins_assert_when_it_is_active(self) -> None:
        specialized = _specialize_asserts(ast.parse(_TWO_SWITCHES_ASSERT))

        with pytest.raises(AssertionError):
            _run_check(specialized, 'g002', 9)

    def it_writes_one_assert_per_gremlin_when_the_same_switch_appears_twice(self) -> None:
        source = "assert (a if __gremlin_active__ == 'g001' else b) or (c if __gremlin_active__ == 'g001' else d)\n"

        specialized = _specialize_asserts(ast.parse(source))

        assert _assert_conditions(specialized) == ['a or c', 'b or d']

    def it_specializes_an_assert_whose_switch_is_only_in_its_message(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_MESSAGE_ASSERT))

        with pytest.raises(AssertionError, match='low'):
            _run_check(specialized, 'g001', 0)

    def it_specializes_an_assert_inside_an_except_handler(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_ASSERT_IN_HANDLER))

        assert _assert_conditions(specialized) == ['n >= 0', 'n > 0']

    def it_specializes_an_assert_inside_a_match_case(self) -> None:
        specialized = _specialize_asserts(ast.parse(_SWITCHED_ASSERT_IN_MATCH_CASE))

        assert _assert_conditions(specialized) == ['n >= 0', 'n > 0']

    @pytest.mark.parametrize(
        'source',
        [
            pytest.param('assert (a if flag else b)\n', id='plain-ternary'),
            pytest.param("assert (a if other == 'g001' else b)\n", id='other-name'),
            pytest.param("assert (a if __gremlin_active__ != 'g001' else b)\n", id='not-equal'),
            pytest.param('assert (a if __gremlin_active__ == wanted else b)\n', id='non-constant-id'),
            pytest.param("assert (a if __gremlin_active__ == 'g001' == wanted else b)\n", id='chained-compare'),
            pytest.param("assert (a if 'g001' == __gremlin_active__ else b)\n", id='reversed-operands'),
        ],
    )
    def it_leaves_an_assert_untouched_when_its_ternary_is_not_a_gremlin_switch(self, source: str) -> None:
        tree = ast.parse(source)

        assert ast.dump(_specialize_asserts(tree)) == ast.dump(ast.parse(source))


def _module_from(name: str, origin: str, active: str = '') -> ModuleType:
    module = ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None, origin=origin)
    module.__dict__['__gremlin_active__'] = active
    return module


@pytest.mark.small
class DescribeGremlinLoaderRewritesSourceForPytestsHook:
    """A module pytest's rewrite hook served keeps pytest's assert messages when the loader compiles source text."""

    ORIGIN = '/project/src/served_mod.py'
    PLAIN_SOURCE = 'def check(n):\n    assert n > 0\n'
    SWITCHED_SOURCE = "def check(n):\n    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"

    def it_explains_a_failed_assert_with_its_operands(self, pytestconfig: pytest.Config) -> None:
        module = _module_from('served_mod', self.ORIGIN)

        GremlinLoader(None, AssertionRewritingHook(pytestconfig), source=self.PLAIN_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'assert -1 > 0'):
            module.check(-1)

    def it_explains_the_active_gremlins_assert_with_its_operands(self, pytestconfig: pytest.Config) -> None:
        module = _module_from('served_switch_mod', self.ORIGIN, active='g001')

        GremlinLoader(None, AssertionRewritingHook(pytestconfig), source=self.SWITCHED_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'assert -1 >= 0'):
            module.check(-1)

    def it_explains_the_original_assert_when_no_gremlin_is_active(self, pytestconfig: pytest.Config) -> None:
        module = _module_from('served_original_mod', self.ORIGIN)

        GremlinLoader(None, AssertionRewritingHook(pytestconfig), source=self.SWITCHED_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'assert 0 > 0'):
            module.check(0)

    def it_records_the_module_as_rewritten_with_the_hook(self, pytestconfig: pytest.Config) -> None:
        hook = AssertionRewritingHook(pytestconfig)

        GremlinLoader(None, hook, source=self.PLAIN_SOURCE).exec_module(_module_from('recorded_mod', self.ORIGIN))

        assert hook._rewritten_names == {'recorded_mod': Path(self.ORIGIN)}

    def it_runs_plain_asserts_when_rewriting_overflows_the_stack(
        self, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def overflow(*_args: object, **_kwargs: object) -> None:
            raise RecursionError

        monkeypatch.setattr('_pytest.assertion.rewrite.rewrite_asserts', overflow)
        module = _module_from('overflow_mod', self.ORIGIN)

        GremlinLoader(None, AssertionRewritingHook(pytestconfig), source=self.PLAIN_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'^$'):
            module.check(-1)

    def it_leaves_asserts_plain_when_another_loader_found_the_module(self) -> None:
        module = _module_from('unserved_mod', self.ORIGIN)

        GremlinLoader(None, object(), source=self.PLAIN_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'^$'):
            module.check(-1)
