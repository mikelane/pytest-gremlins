"""Keep assertion rewriting from displaying a process or subprocess environment.

The guard is a cheap AST heuristic over ``test_*.py`` and ``conftest.py`` files, not a proof.
Session-wide secret scrubbing (#649) is the real defense. Shapes the guard accepts missing:

- aliases held on attributes (``self.env = os.environ``)
- aliases bound by ``for`` targets, ``match`` or ``async with`` bodies
- the environment passed into a call inside the assertion (``assert check(os.environ)``)
- an alias formatted into the assert message (``assert ok, f'bad {env}'``)
- ``os.environ | {...}``, ``os.environ.pop(...)`` and ``patch.dict(os.environ, ...) as env``
- an alias reassigned inside a branch, which drops the alias for later asserts
"""

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
            ('assert ok, os.environ', [1]),
            ("env = dict(os.environ)\nassert ok, f'bad {env}'", []),
            ('assert ok, dict(os.environ)', [1]),
            ('from os import environ\nassert environ == {}', [2]),
            ('from os import environ as process_env\nassert len(process_env) == 0', [2]),
            ("from os import environ\nassert environ['SECRET'] == 'ok'", []),  # pragma: allowlist secret
            ("if (env := os.environ):\n    assert 'SECRET' not in env", [2]),
            ("assert (env := os.environ.copy()) and 'SECRET' not in env", [1]),
            ('assert (env := os.environ) == {}', [1]),
            ("env, other = os.environ, {}\nassert 'SECRET' not in env", [2]),
            ("other, env = {}, os.environ\nassert 'SECRET' not in other", []),
            ("other, env = {}, os.environ\nassert 'SECRET' not in env", [2]),
            ("assert run.call_args[1]['env'] == {}", [1]),
            ("env = run.call_args[1]['env']\nassert 'SECRET' not in env", [2]),
            ("assert run.call_args[0]['env'] == {}", []),
            ("env = {k: v for k, v in os.environ.items() if k}\nassert 'SECRET' not in env", [2]),
            ("env = dict(os.environ)\nfiltered = {k: v for k, v in env.items()}\nassert 'SECRET' not in filtered", [3]),
            ('assert {k: v for k, v in os.environ.items()} == {}', [1]),
            ("env = {k: v for k, v in other.items()}\nassert 'SECRET' not in env", []),
            ("e = {k: v for k, v in os.environ.items()}\nassert e['SECRET'] == 'ok'", []),  # pragma: allowlist secret
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


def _is_named(node: ast.expr, name: str) -> bool:
    return (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name)


def _is_positional_call_kwargs(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 1
        and _is_named(node.value, 'call_args')
    )


def _mapping_draws_on_environment(node: ast.Dict | ast.DictComp, names: set[str]) -> bool:
    if isinstance(node, ast.DictComp):
        return any(_is_environment_source(generator.iter, names) for generator in node.generators)
    return any(
        key is None and _is_environment_source(value, names) for key, value in zip(node.keys, node.values, strict=True)
    )


def _is_environment_source(node: ast.expr, names: set[str]) -> bool:
    if isinstance(node, ast.NamedExpr):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == 'os' and node.attr == 'environ'
    if isinstance(node, ast.Subscript):
        return (
            isinstance(node.slice, ast.Constant)
            and node.slice.value == 'env'
            and (_is_named(node.value, 'kwargs') or _is_positional_call_kwargs(node.value))
        )
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return _mapping_draws_on_environment(node, names)
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


def _bind_alias(target: ast.expr, value: ast.expr, names: set[str]) -> None:
    if isinstance(target, ast.Name):
        if _is_environment_alias(value, names):
            names.add(target.id)
        else:
            names.discard(target.id)
    elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
        for element_target, element_value in zip(target.elts, value.elts, strict=True):
            _bind_alias(element_target, element_value, names)


def _bind_walrus_aliases(expression: ast.expr, names: set[str]) -> None:
    for node in ast.walk(expression):
        if isinstance(node, ast.NamedExpr):
            _bind_alias(node.target, node.value, names)


def _bind_environ_import(statement: ast.ImportFrom, names: set[str]) -> None:
    if statement.module == 'os':
        names.update(alias.asname or alias.name for alias in statement.names if alias.name == 'environ')


def _bind_statement_aliases(statement: ast.ImportFrom | ast.Assign | ast.AnnAssign, names: set[str]) -> None:
    if isinstance(statement, ast.ImportFrom):
        _bind_environ_import(statement, names)
    elif isinstance(statement, ast.Assign):
        for target in statement.targets:
            _bind_alias(target, statement.value, names)
    elif statement.value is not None:
        _bind_alias(statement.target, statement.value, names)


def _is_unsafe_assert(statement: ast.Assert, names: set[str]) -> bool:
    operands = _assertion_operands(statement.test)
    if statement.msg is not None:
        operands.append(statement.msg)
    return any(_is_environment_source(node, names) for node in operands)


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
            if isinstance(statement, (ast.If, ast.While)):
                _bind_walrus_aliases(statement.test, names)
            for body in _nested_statement_bodies(statement):
                unsafe.extend(_scan_assertions(body, names, offset))
        elif isinstance(statement, (ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            _bind_statement_aliases(statement, names)
        elif isinstance(statement, ast.Assert):
            _bind_walrus_aliases(statement.test, names)
            if _is_unsafe_assert(statement, names):
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


# Files whose unsafe environment assertions are deliberate fixtures: this file's checker cases, and the
# child test that test_secret_env_scrub.py runs in a subprocess to prove the session scrub works.
_INTENTIONALLY_UNSAFE_FIXTURE_FILES = frozenset(
    {Path(__file__).resolve(), Path(__file__).resolve().with_name('test_secret_env_scrub.py')}
)


def _unsafe_env_assertions(tests_dir: Path) -> list[str]:
    unsafe: list[str] = []
    for path in sorted({*tests_dir.rglob('test_*.py'), *tests_dir.rglob('conftest.py')}):
        if path.resolve() in _INTENTIONALLY_UNSAFE_FIXTURE_FILES:
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

    def it_scans_conftest_files(self, tmp_path: Path) -> None:
        (tmp_path / 'conftest.py').write_text('assert os.environ == {}\n', encoding='utf-8')
        assert _unsafe_env_assertions(tmp_path) == ['conftest.py:1']

    def it_scans_test_files(self, tmp_path: Path) -> None:
        (tmp_path / 'test_sample.py').write_text('assert os.environ == {}\n', encoding='utf-8')
        assert _unsafe_env_assertions(tmp_path) == ['test_sample.py:1']

    def it_ignores_other_modules(self, tmp_path: Path) -> None:
        (tmp_path / 'helpers.py').write_text('assert os.environ == {}\n', encoding='utf-8')
        assert _unsafe_env_assertions(tmp_path) == []
