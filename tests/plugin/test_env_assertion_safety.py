"""Keep assertion rewriting from displaying a process or subprocess environment."""

from __future__ import annotations

import ast
from pathlib import Path
import textwrap

import pytest


@pytest.mark.small
class DescribeEnvironmentAssertionChecker:
    @pytest.mark.parametrize(
        ('source', 'expected'),
        [
            ("env = dict(os.environ)\nassert 'SECRET' not in env", [2]),
            ('env = os.environ\nassert len(env) == 0', [2]),
            ("env = run.call_args.kwargs['env']\nassert env.items()", [2]),
            ("assert kwargs['env'] == {}", [1]),
            ('env = _prescan_env()\nassert env == {}', [2]),
            ("env = dict(os.environ)\nassert env['SECRET'] == 'ok'", []),
            ("env = dict(os.environ)\nif True:\n    assert 'SECRET' not in env", [3]),
            ("assert os.environ.get('SECRET') is None", [1]),
            ("assert 'SECRET' not in os.environ.keys()", [1]),
            ('assert os.environ.values() == []', [1]),
            ('assert os.environ.items() == []', [1]),
            ('assert os.environ.copy() == {}', [1]),
            ("env = os.environ.copy()\nassert 'SECRET' not in env", [2]),
            ("env = {**os.environ}\nassert 'SECRET' not in env", [2]),
            ("env = _prescan_env().copy()\nassert 'SECRET' not in env", [2]),
            ("env = os.environ\nassert env.get('SECRET') is None", [2]),
            ("env = os.environ\nassert env['SECRET'] == 'ok'", []),  # pragma: allowlist secret
        ],
    )
    def it_flags_only_whole_environment_assertions(self, source: str, expected: list[int]) -> None:
        assert _unsafe_assertions_in_source(source) == expected

    def it_skips_unparseable_embedded_text(self) -> None:
        source = '"""assert os.environ is safe if we think about it"""\n'
        assert _unsafe_assertions_in_source(source) == []

    def it_dedents_embedded_assertions_and_reports_source_lines(self) -> None:
        source = textwrap.dedent('''\
            def fixture():
                snippet = """
                    import os
                    assert os.environ == {}
                """
        ''')
        assert _unsafe_assertions_in_source(source) == [4]


def _is_environment_source(node: ast.expr, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == 'os' and node.attr == 'environ'
    if isinstance(node, ast.Subscript):
        return (
            isinstance(node.slice, ast.Constant)
            and node.slice.value == 'env'
            and (
                (isinstance(node.value, ast.Name) and node.value.id == 'kwargs')
                or (isinstance(node.value, ast.Attribute) and node.value.attr == 'kwargs')
            )
        )
    if isinstance(node, ast.Dict):
        return any(
            key is None and _is_environment_source(value, names)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {'get', 'keys', 'values', 'items', 'copy'}
            and _is_environment_source(node.func.value, names)
        ) or (
            isinstance(node.func, ast.Name)
            and (
                (node.func.id == 'dict' and len(node.args) == 1 and _is_environment_source(node.args[0], names))
                or node.func.id == '_prescan_env'
            )
        )
    return False


def _is_environment_alias(node: ast.expr, names: set[str]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr == 'copy' and _is_environment_source(node.func.value, names)
    return _is_environment_source(node, names) and not (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    )


def _assertion_operands(expression: ast.expr) -> list[ast.expr]:
    operands: list[ast.expr] = []
    for node in ast.walk(expression):
        if isinstance(node, ast.Compare):
            operands.extend([node.left, *node.comparators])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == 'len':
                operands.extend(node.args)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {'get', 'keys', 'values', 'items', 'copy'}:
                operands.append(node)
    if isinstance(expression, (ast.Name, ast.Attribute, ast.Subscript)):
        operands.append(expression)
    return operands


def _assigned_names(statement: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    return [target.id for target in targets if isinstance(target, ast.Name)]


def _nested_statement_bodies(statement: ast.stmt) -> list[list[ast.stmt]]:
    if not isinstance(statement, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
        return []
    bodies = [statement.body]
    if isinstance(statement, (ast.If, ast.For, ast.While, ast.Try)):
        bodies.append(statement.orelse)
    if isinstance(statement, ast.Try):
        bodies.append(statement.finalbody)
        bodies.extend(handler.body for handler in statement.handlers)
    return bodies


def _scan_assertions(statements: list[ast.stmt], names: set[str], offset: int = 0) -> list[int]:
    unsafe: list[int] = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            unsafe.extend(_scan_assertions(statement.body, set(names), offset))
        elif _nested_statement_bodies(statement):
            for body in _nested_statement_bodies(statement):
                unsafe.extend(_scan_assertions(body, names, offset))
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None:
            for name in _assigned_names(statement):
                if _is_environment_alias(statement.value, names):
                    names.add(name)
                else:
                    names.discard(name)
        elif isinstance(statement, ast.Assert) and any(
            _is_environment_source(node, names) for node in _assertion_operands(statement.test)
        ):
            unsafe.append(statement.lineno + offset)
    return unsafe


def _embedded_assertions(tree: ast.AST) -> list[int]:
    unsafe: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if 'assert ' not in node.value or 'os.environ' not in node.value:
            continue
        try:
            snippet = ast.parse(textwrap.dedent(node.value))
        except SyntaxError:
            continue
        unsafe.extend(_scan_assertions(snippet.body, set(), node.lineno - 1))
    return unsafe


def _unsafe_assertions_in_source(source: str) -> list[int]:
    tree = ast.parse(source)
    return _scan_assertions(tree.body, set()) + _embedded_assertions(tree)


def _unsafe_env_assertions(tests_dir: Path) -> list[str]:
    unsafe: list[str] = []
    for path in tests_dir.rglob('test_*.py'):
        if path == Path(__file__).resolve():  # This file contains intentionally unsafe checker fixtures.
            continue
        unsafe.extend(
            f'{path.relative_to(tests_dir)}:{line}'
            for line in _unsafe_assertions_in_source(path.read_text(encoding='utf-8'))
        )
    return unsafe


@pytest.mark.medium
class DescribeEnvironmentAssertionSafety:
    """Assertions should expose only the scalar under test."""

    def it_keeps_environment_mappings_out_of_assertions(self) -> None:
        """A failed assertion must not print a full environment mapping."""
        assert _unsafe_env_assertions(Path(__file__).resolve().parents[1]) == []
