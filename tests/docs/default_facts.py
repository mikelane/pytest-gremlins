"""Facts for drift check 1c: the default each option has in the code and the default the docs state for it."""

from __future__ import annotations

from pathlib import Path
import re

from pytest_gremlins.plugin import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_COVERAGE_TIMEOUT_SECONDS,
    DEFAULT_MUTANT_TIMEOUT_SECONDS,
    DEFAULT_REPORT_FORMATS,
)
from pytest_gremlins.reporting.html import resolve_html_output_path

from .docs_facts import (
    default_cells,
    registered_help_defaults,
    registered_options,
    toml_default_comments,
)

# The phrase the docs use for each option or key that has no code default. Each name has exactly one, so a wrong
# phrase fails even when it is valid for another option.
UNSET_PHRASE_BY_NAME: dict[str, str] = {
    '--gremlin-operators': 'all',
    '--gremlin-targets': 'auto-discovered',
    '--gremlin-exclude': 'none',
    '--gremlin-explain': 'none',
    '--gremlin-max-pardons-pct': 'disabled',
    '--max-pardons': 'disabled',
    'operators': 'all',
    'paths': 'auto-discovered',
    'exclude': '[]',
    'workers': 'not set',
    'max_pardons': 'no limit',
    'max-pardons-pct': 'no limit',
}

CONFIG_KEY_TO_FLAG: dict[str, str] = {
    'operators': '--gremlin-operators',
    'paths': '--gremlin-targets',
    'exclude': '--gremlin-exclude',
    'workers': '--gremlin-workers',
    'cache': '--gremlin-cache',
    'report': '--gremlin-report',
    'batch_size': '--gremlin-batch-size',
    'max_pardons': '--max-pardons',
    'max-pardons-pct': '--gremlin-max-pardons-pct',
    'coverage_timeout': '--gremlin-coverage-timeout',
    'mutant_timeout': '--gremlin-mutant-timeout',
}


def as_text(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list | tuple):
        return ','.join(value)
    return str(value)


def normalize(cell: str) -> str:
    return cell.strip().strip('`').strip('"\'').lower()


_PROJECT_ROOT = Path('project')
HTML_REPORT_DIR = resolve_html_output_path(_PROJECT_ROOT, None).parent.relative_to(_PROJECT_ROOT).as_posix() + '/'

CODE_DEFAULTS: dict[str, object] = {
    '--gremlins-html-dir': HTML_REPORT_DIR,
    '--gremlin-batch-size': DEFAULT_BATCH_SIZE,
    '--gremlin-report': DEFAULT_REPORT_FORMATS,
    '--gremlin-coverage-timeout': DEFAULT_COVERAGE_TIMEOUT_SECONDS,
    '--gremlin-mutant-timeout': DEFAULT_MUTANT_TIMEOUT_SECONDS,
}


def hard_code_defaults() -> dict[str, str]:
    """Return the concrete default of each option that has one, as text."""
    parser_defaults = {option.flag: option.default for option in registered_options() if option.default is not None}
    return {flag: as_text(value) for flag, value in {**parser_defaults, **CODE_DEFAULTS}.items()}


def default_mismatches(documented: dict[str, str], expected_by_name: dict[str, str | None]) -> list[str]:
    """Describe each name whose documented default is not its code default."""
    problems: list[str] = []
    for name, cell in documented.items():
        expected = expected_by_name.get(name)
        shown = normalize(cell)
        phrase = UNSET_PHRASE_BY_NAME.get(name)
        if expected is not None and shown != expected.lower():
            problems.append(f'{name}: documented {shown!r}, code default {expected!r}')
        elif expected is None and shown != phrase:
            problems.append(
                f'{name}: documented {shown!r}, but the code has no default '
                f'(use {phrase!r}; register a phrase in UNSET_PHRASE_BY_NAME if none)'
            )
    return problems


def flag_defaults_in_docs() -> dict[str, str]:
    return {name: cell for name, cell in default_cells().items() if name.startswith('--')}


def key_defaults_in_docs() -> dict[str, str]:
    return {name: cell for name, cell in default_cells().items() if not name.startswith('--')}


def expected_flag_defaults() -> dict[str, str | None]:
    hard = hard_code_defaults()
    return {flag: hard.get(flag, registered_help_defaults().get(flag)) for flag in flag_defaults_in_docs()}


def expected_key_defaults() -> dict[str, str | None]:
    hard = hard_code_defaults()
    return {key: hard.get(CONFIG_KEY_TO_FLAG.get(key, '')) for key in key_defaults_in_docs()}


# What may follow the table's default in a ``# Default:`` comment: nothing, or prose such as ``all operators`` or
# ``not set (one at a time ...)``. A digit, ``.``, quote or comma would make the comment state a different value.
_END_OF_STATED_DEFAULT = r'(?=$|\s|\()'


def default_comment_mismatches(comments: dict[str, str], table_cells: dict[str, str]) -> list[str]:
    """Describe each TOML ``# Default:`` comment that does not start with the default its key's table cell states."""
    problems: list[str] = []
    for key, comment in comments.items():
        if key not in table_cells:
            problems.append(f'{key}: the TOML example says "Default: {comment}" but the options table has no such key')
            continue
        stated = normalize(table_cells[key])
        if not re.match(re.escape(stated) + _END_OF_STATED_DEFAULT, normalize(comment)):
            problems.append(f'{key}: the TOML example says "Default: {comment}", the options table says {stated!r}')
    return problems


def toml_default_comment_mismatches() -> list[str]:
    """Describe each ``# Default:`` comment on the configuration page that disagrees with its options table row."""
    return default_comment_mismatches(toml_default_comments(), key_defaults_in_docs())
