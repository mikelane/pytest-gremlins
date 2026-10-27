"""An assert holding gremlin switches becomes one plain assert per gremlin so pytest can explain it (#603).

Every test drives ``GremlinLoader.exec_module`` with the assertion-rewrite hook that pytest uses, then observes
the loaded module: which branch an assert runs and what its failure message says.
"""

from __future__ import annotations

import importlib.machinery
from pathlib import Path
from types import ModuleType
from typing import (
    Protocol,
    cast,
)

from _pytest.assertion.rewrite import AssertionRewritingHook
import pytest

from pytest_gremlins.instrumentation.origin_finder import GremlinLoader

_ORIGIN = '/project/src/served_mod.py'


class _ResourceReaderSource(Protocol):
    def get_resource_reader(self, fullname: str) -> object: ...


class _PathReader(Protocol):
    path: Path


_SWITCHED_ASSERT = (
    "def check(n):\n    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0), 'bad'\n    return n\n"
)

_TWO_SWITCHES_ASSERT = (
    'def check(n):\n'
    "    assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0) and "
    "(n < 9 if __gremlin_active__ == 'g002' else n < 10)\n"
    '    return n\n'
)

_SAME_SWITCH_TWICE = (
    'def check(a, b, c, d):\n'
    "    assert (a if __gremlin_active__ == 'g001' else b) or (c if __gremlin_active__ == 'g001' else d)\n"
)

_SWITCHED_MESSAGE_ASSERT = "def check(n):\n    assert n > 0, ('low' if __gremlin_active__ == 'g001' else 'bad')\n"

_SWITCHED_ASSERT_IN_HANDLER = (
    'def check(n):\n'
    '    try:\n'
    '        raise ValueError\n'
    '    except ValueError:\n'
    "        assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
)

_SWITCHED_ASSERT_IN_MATCH_CASE = (
    'def check(n):\n'
    '    match n:\n'
    '        case _:\n'
    "            assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
)

_DEEP_ELIF_BRANCHES = 600


def _deep_elif_with_switched_assert_at_the_bottom() -> str:
    branches = ''.join(f'    elif flags[{index}]:\n        return {index}\n' for index in range(1, _DEEP_ELIF_BRANCHES))
    bottom = "    else:\n        assert (n >= 0 if __gremlin_active__ == 'g001' else n > 0)\n"
    return f'def check(flags, n):\n    if flags[0]:\n        return 0\n{branches}{bottom}'


_NESTING_DEEPER_THAN_THE_STACK = 1500


def _switched_assert_nested_deeper_than_the_stack() -> str:
    nested = "(n >= 0 if __gremlin_active__ == 'g001' else n > 0)"
    negations = 'not ' * _NESTING_DEEPER_THAN_THE_STACK
    return f'def check(n):\n    assert {negations}{nested}\n    return n\n'


def _lookalike_assert(condition: str) -> str:
    return f'def check(flag, other, wanted):\n    assert (True if {condition} else False)\n'


def _load(source: str, config: pytest.Config, *, name: str, active: str = '') -> ModuleType:
    module = ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None, origin=_ORIGIN)
    module.__dict__['__gremlin_active__'] = active
    GremlinLoader(None, AssertionRewritingHook(config), source=source).exec_module(module)
    return module


@pytest.mark.small
class DescribeGremlinLoaderSpecializesSwitchedAsserts:
    def it_runs_the_active_gremlins_assert(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT, pytestconfig, name='active_mod', active='g001')

        assert module.check(0) == 0

    def it_runs_the_original_assert_when_no_gremlin_is_active(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT, pytestconfig, name='original_mod')

        with pytest.raises(AssertionError, match='bad'):
            module.check(0)

    def it_explains_the_active_gremlins_assert_with_its_operands(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT, pytestconfig, name='explained_active_mod', active='g001')

        with pytest.raises(AssertionError, match=r'assert -1 >= 0'):
            module.check(-1)

    def it_explains_the_original_assert_with_its_operands(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT, pytestconfig, name='explained_original_mod')

        with pytest.raises(AssertionError, match=r'assert 0 > 0'):
            module.check(0)

    def it_leaves_an_assert_without_switches_explained_as_pytest_does(self, pytestconfig: pytest.Config) -> None:
        module = _load('def check(n):\n    assert n > 0\n', pytestconfig, name='plain_mod')

        with pytest.raises(AssertionError, match=r'assert -1 > 0'):
            module.check(-1)

    def it_specializes_an_assert_at_the_bottom_of_a_very_deep_elif_chain(self, pytestconfig: pytest.Config) -> None:
        module = _load(
            _deep_elif_with_switched_assert_at_the_bottom(), pytestconfig, name='deep_elif_mod', active='g001'
        )

        with pytest.raises(AssertionError, match=r'assert -1 >= 0'):
            module.check([False] * _DEEP_ELIF_BRANCHES, -1)

    def it_keeps_the_active_gremlin_when_specializing_an_assert_overflows_the_stack(
        self, pytestconfig: pytest.Config
    ) -> None:
        module = _load(
            _switched_assert_nested_deeper_than_the_stack(), pytestconfig, name='overflow_assert_mod', active='g001'
        )

        assert module.check(0) == 0

    def it_still_fails_the_active_gremlins_assert_when_specializing_it_overflows_the_stack(
        self, pytestconfig: pytest.Config
    ) -> None:
        module = _load(
            _switched_assert_nested_deeper_than_the_stack(), pytestconfig, name='overflow_guard_mod', active='g001'
        )

        with pytest.raises(AssertionError):
            module.check(-1)


@pytest.mark.small
class DescribeGremlinLoaderResolvesEverySwitchAnAssertHolds:
    """Every gremlin switch an assert holds is resolved, and nothing that merely looks like one is touched."""

    @pytest.mark.parametrize(
        ('active', 'value', 'message'),
        [
            pytest.param('g001', -1, r'assert \(-1 >= 0\)', id='first-gremlin'),
            pytest.param('g002', 9, r'assert \(9 > 0 and 9 < 9\)', id='second-gremlin'),
            pytest.param('', 0, r'assert \(0 > 0', id='original'),
        ],
    )
    def it_runs_the_assert_of_the_active_gremlin_and_explains_it(
        self, pytestconfig: pytest.Config, active: str, value: int, message: str
    ) -> None:
        module = _load(_TWO_SWITCHES_ASSERT, pytestconfig, name=f'two_switch_{active or "none"}_mod', active=active)

        with pytest.raises(AssertionError, match=message):
            module.check(value)

    def it_runs_the_original_assert_for_an_id_no_switch_names(self, pytestconfig: pytest.Config) -> None:
        module = _load(_TWO_SWITCHES_ASSERT, pytestconfig, name='unknown_id_mod', active='g999')

        assert module.check(5) == 5

    def it_resolves_a_switch_that_appears_twice_in_one_assert(self, pytestconfig: pytest.Config) -> None:
        active = _load(_SAME_SWITCH_TWICE, pytestconfig, name='twice_active_mod', active='g001')
        original = _load(_SAME_SWITCH_TWICE, pytestconfig, name='twice_original_mod')

        with pytest.raises(AssertionError, match=r'False or False'):
            active.check(False, True, False, True)
        original.check(False, True, False, True)

    def it_specializes_an_assert_whose_switch_is_only_in_its_message(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_MESSAGE_ASSERT, pytestconfig, name='message_switch_mod', active='g001')

        with pytest.raises(AssertionError, match='low'):
            module.check(0)

    def it_specializes_an_assert_inside_an_except_handler(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT_IN_HANDLER, pytestconfig, name='handler_mod', active='g001')

        with pytest.raises(AssertionError, match=r'assert -1 >= 0'):
            module.check(-1)

    def it_specializes_an_assert_inside_a_match_case(self, pytestconfig: pytest.Config) -> None:
        module = _load(_SWITCHED_ASSERT_IN_MATCH_CASE, pytestconfig, name='match_case_mod', active='g001')

        with pytest.raises(AssertionError, match=r'assert -1 >= 0'):
            module.check(-1)

    @pytest.mark.parametrize(
        ('condition', 'active'),
        [
            pytest.param('flag', 'g001', id='plain-ternary'),
            pytest.param("other == 'g001'", 'g001', id='other-name'),
            pytest.param("__gremlin_active__ != 'g001'", 'g001', id='not-equal'),
        ],
    )
    def it_takes_the_else_branch_of_a_ternary_that_is_not_a_gremlin_switch(
        self, pytestconfig: pytest.Config, condition: str, active: str
    ) -> None:
        module = _load(_lookalike_assert(condition), pytestconfig, name='lookalike_else_mod', active=active)

        with pytest.raises(AssertionError):
            module.check(False, 'x', 'g001')

    def it_evaluates_the_whole_chain_of_a_chained_compare_that_names_a_gremlin(
        self, pytestconfig: pytest.Config
    ) -> None:
        module = _load(
            _lookalike_assert("__gremlin_active__ == 'g001' == wanted"),
            pytestconfig,
            name='chained_compare_mod',
            active='g001',
        )

        with pytest.raises(AssertionError):
            module.check(False, 'x', 'g002')

    @pytest.mark.parametrize(
        ('condition', 'active'),
        [
            pytest.param("__gremlin_active__ != 'g001'", 'g002', id='not-equal-other-id'),
            pytest.param('__gremlin_active__ == wanted', 'g001', id='non-constant-id'),
            pytest.param("'g001' == __gremlin_active__", 'g001', id='reversed-operands'),
        ],
    )
    def it_takes_the_if_branch_of_a_ternary_that_is_not_a_gremlin_switch(
        self, pytestconfig: pytest.Config, condition: str, active: str
    ) -> None:
        module = _load(_lookalike_assert(condition), pytestconfig, name='lookalike_if_mod', active=active)

        module.check(False, 'x', 'g001')


@pytest.mark.small
class DescribeGremlinLoaderRewritesSourceForPytestsHook:
    """A module pytest's rewrite hook served keeps pytest's assert messages when the loader compiles source text."""

    PLAIN_SOURCE = 'def check(n):\n    assert n > 0\n'

    def it_explains_asserts_when_pytest_renames_its_hook_class(self, pytestconfig: pytest.Config) -> None:
        class RenamedRewriteLoader(AssertionRewritingHook):
            pass

        RenamedRewriteLoader.__module__ = '_pytest.assertion.rewrite'
        module = ModuleType('renamed_hook_mod')
        module.__spec__ = importlib.machinery.ModuleSpec('renamed_hook_mod', None, origin=_ORIGIN)

        GremlinLoader(None, RenamedRewriteLoader(pytestconfig), source=self.PLAIN_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'assert -1 > 0'):
            module.check(-1)

    def it_keeps_package_data_reachable_through_the_hook_for_a_module_it_rewrote(
        self, pytestconfig: pytest.Config
    ) -> None:
        # The hook's get_resource_reader looks the module up in its rewritten names, so a missing record would
        # break importlib.resources for every module the loader serves.
        hook = AssertionRewritingHook(pytestconfig)
        module = ModuleType('recorded_mod')
        module.__spec__ = importlib.machinery.ModuleSpec('recorded_mod', None, origin=_ORIGIN)
        loader = GremlinLoader(None, hook, source=self.PLAIN_SOURCE)

        loader.exec_module(module)

        reader = cast('_PathReader', cast('_ResourceReaderSource', loader).get_resource_reader('recorded_mod'))
        assert reader.path == Path(_ORIGIN).parent

    def it_runs_plain_asserts_when_rewriting_overflows_the_stack(
        self, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def overflow(*_args: object, **_kwargs: object) -> None:
            raise RecursionError

        monkeypatch.setattr('_pytest.assertion.rewrite.rewrite_asserts', overflow)

        module = _load(self.PLAIN_SOURCE, pytestconfig, name='overflow_mod')

        with pytest.raises(AssertionError, match=r'^$'):
            module.check(-1)

    def it_leaves_asserts_plain_when_another_loader_found_the_module(self) -> None:
        module = ModuleType('unserved_mod')
        module.__spec__ = importlib.machinery.ModuleSpec('unserved_mod', None, origin=_ORIGIN)

        GremlinLoader(None, object(), source=self.PLAIN_SOURCE).exec_module(module)

        with pytest.raises(AssertionError, match=r'^$'):
            module.check(-1)
