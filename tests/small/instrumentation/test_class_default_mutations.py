"""Tests for boolean mutations in class attribute defaults.

Regression tests for GitHub issue #91: boolean mutations in dataclass
field defaults (e.g., `last: bool = False`) are incorrectly reported
as surviving when they should be zapped.

The switching expression itself works correctly in class body context.
These tests verify the instrumentation layer handles class-level constants.
"""

from __future__ import annotations

import ast

from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.operators.boolean import BooleanOperator


class TestTransformerDetectsClassDefaultBooleans:
    """Verify the transformer creates gremlins for boolean defaults in class bodies."""

    def test_creates_gremlin_for_false_default_in_dataclass(self):
        source = """
from dataclasses import dataclass

@dataclass
class Addr:
    name: str = ''
    last: bool = False
"""
        gremlins, _tree = transform_source(source, 'example.py', [BooleanOperator()])

        boolean_gremlins = [g for g in gremlins if g.description == 'False to True']
        assert len(boolean_gremlins) == 1
        assert boolean_gremlins[0].line_number == 7

    def test_creates_gremlin_for_true_default_in_dataclass(self):
        source = """
from dataclasses import dataclass

@dataclass
class Range:
    start: int = 0
    from0: bool = True
"""
        gremlins, _tree = transform_source(source, 'example.py', [BooleanOperator()])

        boolean_gremlins = [g for g in gremlins if g.description == 'True to False']
        assert len(boolean_gremlins) == 1
        assert boolean_gremlins[0].line_number == 7

    def test_creates_gremlins_for_multiple_boolean_defaults(self):
        source = """
from dataclasses import dataclass

@dataclass
class Config:
    enabled: bool = True
    verbose: bool = False
    strict: bool = True
"""
        gremlins, _tree = transform_source(source, 'example.py', [BooleanOperator()])

        assert len(gremlins) == 3

    def test_creates_gremlin_for_plain_class_boolean_default(self):
        source = """
class MyClass:
    active: bool = False
"""
        gremlins, _tree = transform_source(source, 'example.py', [BooleanOperator()])

        boolean_gremlins = [g for g in gremlins if g.description == 'False to True']
        assert len(boolean_gremlins) == 1


class TestSwitchingExpressionWorksInClassBody:
    """Verify that the switching expression evaluates correctly in a class body context.

    This is critical: class attribute defaults are evaluated at class definition time
    (import time), not at function call time. The __gremlin_active__ variable must be
    accessible from the class body's scope.
    """

    def test_class_default_uses_original_when_no_gremlin_active(self):
        source = """
from dataclasses import dataclass

@dataclass
class Addr:
    last: bool = False
"""
        _gremlins, tree = transform_source(source, 'example.py', [BooleanOperator()])
        ast.fix_missing_locations(tree)

        code = compile(tree, 'example.py', 'exec')
        # NOTE: exec() is used intentionally to test AST-generated instrumented code.
        # This is testing mutation switching infrastructure, not running untrusted input.
        exec_globals: dict[str, object] = {'__gremlin_active__': None}
        exec(code, exec_globals)  # noqa: S102

        Addr = exec_globals['Addr']  # noqa: N806
        instance = Addr()  # type: ignore[operator]
        assert instance.last is False  # type: ignore[union-attr]

    def test_class_default_uses_mutation_when_gremlin_active(self):
        source = """
from dataclasses import dataclass

@dataclass
class Addr:
    last: bool = False
"""
        gremlins, tree = transform_source(source, 'example.py', [BooleanOperator()])
        ast.fix_missing_locations(tree)

        # Activate the gremlin that flips False to True
        gremlin_id = gremlins[0].gremlin_id
        code = compile(tree, 'example.py', 'exec')
        # NOTE: exec() is used intentionally to test AST-generated instrumented code.
        exec_globals: dict[str, object] = {'__gremlin_active__': gremlin_id}
        exec(code, exec_globals)  # noqa: S102

        Addr = exec_globals['Addr']  # noqa: N806
        instance = Addr()  # type: ignore[operator]
        assert instance.last is True  # type: ignore[union-attr]

    def test_true_default_flips_to_false_when_gremlin_active(self):
        source = """
from dataclasses import dataclass

@dataclass
class Range:
    from0: bool = True
"""
        gremlins, tree = transform_source(source, 'example.py', [BooleanOperator()])
        ast.fix_missing_locations(tree)

        gremlin_id = gremlins[0].gremlin_id
        code = compile(tree, 'example.py', 'exec')
        # NOTE: exec() is used intentionally to test AST-generated instrumented code.
        exec_globals: dict[str, object] = {'__gremlin_active__': gremlin_id}
        exec(code, exec_globals)  # noqa: S102

        Range = exec_globals['Range']  # noqa: N806
        instance = Range()  # type: ignore[operator]
        assert instance.from0 is False  # type: ignore[union-attr]
