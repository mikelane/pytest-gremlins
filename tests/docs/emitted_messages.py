"""Find the ``pytest-gremlins:`` messages the plugin can print and match quoted docs lines against them.

A message is a string constant or f-string in the source with a line that starts with ``MESSAGE_PREFIX``.
Placeholders in it (f-string fields, ``%s``-style and ``{}``-style format fields) stand for any text.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

MESSAGE_PREFIX = 'pytest-gremlins:'

_WILDCARD = '\x00'
_FORMAT_FIELD = re.compile(r'%[sdrif]|\{[^{}]*\}')
# A message inside a quoted string of generated code, e.g. print(f'pytest-gremlins: ...') in an embedded script.
_QUOTED_MESSAGE = re.compile(r"""(['"])(?:\\[nr])*(pytest-gremlins:.*?)\1""")
_ELLIPSIS = re.compile(r'\s*(?:\.\.\.|…)$')


def message_templates(source: str) -> list[str]:
    """Return one template per message line in ``source``, with each placeholder replaced by ``\\x00``."""
    tree = ast.parse(source)
    skipped = _docstring_nodes(tree) | _f_string_parts(tree)
    templates: list[str] = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        text = _template_text(node)
        if text is not None:
            templates.extend(message for line in text.split('\n') for message in _messages_in_line(line))
    return [template for template in templates if _has_stable_phrase(template)]


def message_templates_under(root: Path) -> list[str]:
    """Return the message templates of every Python file under ``root``."""
    return [
        template
        for path in sorted(root.rglob('*.py'))
        for template in message_templates(path.read_text(encoding='utf-8'))
    ]


def line_is_emittable(doc_line: str, templates: list[str], *, continues: bool) -> bool:
    """Return whether ``doc_line`` is a message the code can emit.

    A line that the docs elide with ``...`` or wrap onto a following line (``continues``) only has to be the
    start of a message.
    """
    text = doc_line.strip()
    elided = _ELLIPSIS.search(text)
    if elided:
        text = text[: elided.start()]
    if elided or continues:
        return any(_starts_a_message(text, template) for template in templates)
    return any(re.fullmatch(_pattern(template), text) for template in templates)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _f_string_parts(tree: ast.AST) -> set[int]:
    return {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node)
        if part is not node
    }


def _template_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _FORMAT_FIELD.sub(_WILDCARD, node.value)
    if isinstance(node, ast.JoinedStr):
        return ''.join(
            part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else _WILDCARD
            for part in node.values
        )
    return None


def _pattern(template: str) -> str:
    return '.*'.join(re.escape(literal) for literal in template.split(_WILDCARD))


def _messages_in_line(line: str) -> list[str]:
    line = line.lstrip('\r')
    if line.startswith(MESSAGE_PREFIX):
        return [line.rstrip()]
    return [match.group(2).rstrip() for match in _QUOTED_MESSAGE.finditer(line)]


def _has_stable_phrase(template: str) -> bool:
    """Return whether the template says something beyond the prefix and its placeholders.

    A message that is only ``pytest-gremlins:`` plus a placeholder matches every docs line, so it proves nothing.
    The source needs a stable leading phrase for the docs to be checked against it.
    """
    return bool(template.removeprefix(MESSAGE_PREFIX).replace(_WILDCARD, '').strip())


def _starts_a_message(text: str, template: str) -> bool:
    literals = template.split(_WILDCARD)
    if template.endswith(_WILDCARD) and re.fullmatch(_pattern(template), text):
        return True
    for index, literal in enumerate(literals):
        consumed = ''.join(f'{re.escape(earlier)}.*' for earlier in literals[:index])
        shortest_start = 1 if index else 0
        started = '|'.join(re.escape(literal[:length]) for length in range(shortest_start, len(literal) + 1))
        if started and re.fullmatch(f'{consumed}(?:{started})', text):
            return True
    return False
