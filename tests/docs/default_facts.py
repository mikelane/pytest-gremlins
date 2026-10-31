"""Facts for drift check 1c: the default each option has in the code and the default the docs state for it."""

from __future__ import annotations

from pytest_gremlins.plugin import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_COVERAGE_TIMEOUT_SECONDS,
    DEFAULT_MUTANT_TIMEOUT_SECONDS,
    DEFAULT_REPORT_FORMATS,
)

from .docs_facts import (
    default_cells,
    registered_help_defaults,
    registered_options,
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
    return cell.strip().strip('`').strip('"').lower()


CODE_DEFAULTS: dict[str, object] = {
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
        if expected is not None and shown != expected.lower():
            problems.append(f'{name}: documented {shown!r}, code default {expected!r}')
        elif expected is None and shown != UNSET_PHRASE_BY_NAME.get(name):
            problems.append(
                f'{name}: documented {shown!r}, but the code has no default '
                f'(use {UNSET_PHRASE_BY_NAME.get(name)!r}; register a phrase in UNSET_PHRASE_BY_NAME if none)'
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
