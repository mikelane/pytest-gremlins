#!/usr/bin/env python3
"""Action cookbook drift check: compare ``docs/cookbook/github-action.md`` with the action's ``action.yml``.

Takes the path to ``action.yml`` (fetched from ``mikelane/pytest-gremlins-action``) and the path to the
cookbook page. The inputs and outputs the cookbook lists must match the action's, with the same names and
the same defaults.

An action input with no ``default`` has the default ``''`` (that is what GitHub uses), so the cookbook
documents it as ``''`` in a code span, the same as an input whose default is the empty string.

Exit codes: 0 when they match, 1 on drift (each drift line is printed on stdout with a ``DRIFT:`` prefix),
2 when either file cannot be read or parsed, or anything unexpected goes wrong (the reason is printed on
stderr). Exit 2 is never drift: a cookbook whose tables cannot be found fails loudly instead of passing
vacuously.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

import yaml  # type: ignore[import-untyped]

INPUTS_HEADING = 'Action Inputs'
OUTPUTS_HEADING = 'Action Outputs'
INPUT_COLUMNS = ('input', 'default')
OUTPUT_COLUMNS = ('output',)
ESCAPED_PIPE = '\\|'
PIPE_PLACEHOLDER = '\x00'
CODE_SPAN = re.compile(r'`([^`]*)`')
SECTION_END = re.compile(r'#{1,2} ')
FENCE_MARKERS = ('```', '~~~')
DRIFT_PREFIX = 'DRIFT: '


class ParseError(Exception):
    """Raised when action.yml or the cookbook cannot be read as the expected structure."""


@dataclass(frozen=True)
class ActionSpec:
    """Inputs (name to default; a missing default is ``''``) and output names of an action."""

    inputs: dict[str, str]
    outputs: frozenset[str]


@dataclass(frozen=True)
class CookbookSpec:
    """Inputs (name to default) and output names that the cookbook documents."""

    inputs: dict[str, str]
    outputs: frozenset[str]


def _default_as_string(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def parse_action(text: str) -> ActionSpec:
    """Read the input and output names and input defaults from action.yml text."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ParseError(f'action.yml is not valid YAML: {error}') from error
    if not isinstance(document, dict):
        raise ParseError('action.yml is not a YAML mapping')
    inputs = document.get('inputs')
    if not inputs:
        raise ParseError('action.yml has no inputs section')
    outputs = document.get('outputs') or {}
    if not isinstance(inputs, dict):
        raise ParseError('action.yml `inputs` is not a mapping')
    if not isinstance(outputs, dict):
        raise ParseError('action.yml `outputs` is not a mapping')
    return ActionSpec(
        inputs={str(name): _input_default(str(name), spec) for name, spec in inputs.items()},
        outputs=frozenset(str(name) for name in outputs),
    )


def _input_default(name: str, spec: object) -> str:
    if spec is None:
        return ''
    if not isinstance(spec, dict):
        raise ParseError(f'action.yml input `{name}` is not a mapping')
    return _default_as_string(spec.get('default'))


def _section_lines(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = lines.index(f'## {heading}')
    except ValueError:
        raise ParseError(f'cookbook has no "## {heading}" heading') from None
    section: list[str] = []
    in_fence = False
    for line in lines[start + 1 :]:
        if line.startswith(FENCE_MARKERS):
            in_fence = not in_fence
        elif not in_fence and SECTION_END.match(line):
            break
        elif not in_fence:
            section.append(line)
    return section


def _table_rows(section: list[str]) -> list[list[str]]:
    rows = []
    for line in section:
        if not line.startswith('|'):
            continue
        protected = line.replace(ESCAPED_PIPE, PIPE_PLACEHOLDER)
        cells = [cell.strip().replace(PIPE_PLACEHOLDER, '|') for cell in protected.strip('|').split('|')]
        rows.append(cells)
    return rows


def _code_text(cell: str, column: str, heading: str) -> str:
    match = CODE_SPAN.fullmatch(cell)
    if match is None:
        raise ParseError(f'"{heading}" {column} cell {cell!r} is not in code formatting (backticks)')
    return match.group(1)


def _unquote(default: str) -> str:
    if len(default) >= 2 and default[0] == default[-1] == "'":  # noqa: PLR2004
        return default[1:-1]
    return default


def _table_body(markdown: str, heading: str, expected_columns: tuple[str, ...]) -> list[list[str]]:
    rows = _table_rows(_section_lines(markdown, heading))
    if not rows:
        raise ParseError(f'"{heading}" has no table')
    header, *rest = rows
    columns = tuple(cell.lower() for cell in header[: len(expected_columns)])
    if columns != expected_columns:
        raise ParseError(f'"{heading}" table columns are {header!r}, expected {expected_columns!r} first')
    body = [row for row in rest if not set(''.join(row)) <= set('-: ')]
    if not body:
        raise ParseError(f'"{heading}" table has no rows')
    return body


def parse_cookbook(markdown: str) -> CookbookSpec:
    """Read the documented inputs (with defaults) and outputs from the cookbook markdown."""
    input_rows = _table_body(markdown, INPUTS_HEADING, INPUT_COLUMNS)
    output_rows = _table_body(markdown, OUTPUTS_HEADING, OUTPUT_COLUMNS)
    inputs: dict[str, str] = {}
    for row in input_rows:
        name = _code_text(row[0], 'name', INPUTS_HEADING)
        if len(row) < len(INPUT_COLUMNS):
            raise ParseError(f'"{INPUTS_HEADING}" row for `{name}` has no default cell')
        if name in inputs:
            raise ParseError(f'"{INPUTS_HEADING}" documents input `{name}` twice')
        inputs[name] = _unquote(_code_text(row[1], f'`{name}` default', INPUTS_HEADING))
    outputs = frozenset(_code_text(row[0], 'name', OUTPUTS_HEADING) for row in output_rows)
    return CookbookSpec(inputs=inputs, outputs=outputs)


def _compare_names(kind: str, in_action: frozenset[str], in_cookbook: frozenset[str]) -> list[str]:
    return [
        *(f'{kind} `{name}` is in action.yml but not in the cookbook' for name in sorted(in_action - in_cookbook)),
        *(f'{kind} `{name}` is in the cookbook but not in action.yml' for name in sorted(in_cookbook - in_action)),
    ]


def compare(action: ActionSpec, cookbook: CookbookSpec) -> list[str]:
    """Return one readable line per difference in names or defaults; empty when they match."""
    drift = _compare_names('input', frozenset(action.inputs), frozenset(cookbook.inputs))
    for name in sorted(set(action.inputs) & set(cookbook.inputs)):
        if action.inputs[name] != cookbook.inputs[name]:
            expected, documented = action.inputs[name], cookbook.inputs[name]
            drift.append(f'input `{name}` default: action.yml has {expected!r}, cookbook has {documented!r}')
    drift.extend(_compare_names('output', action.outputs, cookbook.outputs))
    return drift


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise ParseError(f'cannot read {path}: {error}') from error


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action_yml', type=Path, help="path to the action repo's action.yml")
    parser.add_argument('cookbook', type=Path, help='path to docs/cookbook/github-action.md')
    args = parser.parse_args(argv)
    try:
        drift = compare(parse_action(_read(args.action_yml)), parse_cookbook(_read(args.cookbook)))
    except ParseError as error:
        print(f'could not check the cookbook: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with drift (exit 1)
        print(f'could not check the cookbook: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if drift:
        print(f'{args.cookbook} has drifted from {args.action_yml}:')
        for line in drift:
            print(f'{DRIFT_PREFIX}{line}')
        return 1
    print('The cookbook inputs and outputs match action.yml.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
