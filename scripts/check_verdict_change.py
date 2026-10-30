"""Fail a PR whose code changes a gremlin verdict without raising a cache version (#876)."""

from __future__ import annotations

from collections import Counter
from collections.abc import (
    Collection,
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_DIR = 'src/pytest_gremlins/'

CACHE_VERSION_ADVICE = (
    'The set of gremlins changed, so the change alters what gets mutated: raise CACHE_VERSION in '
    'src/pytest_gremlins/cache/versions.py.'
)
RUNNER_FIDELITY_ADVICE = (
    'Only verdicts changed, so the change alters test execution or the outcome-to-verdict mapping: raise '
    'RUNNER_FIDELITY_VERSION in src/pytest_gremlins/cache/incremental.py. If it alters what gets mutated '
    'instead, raise CACHE_VERSION in src/pytest_gremlins/cache/versions.py.'
)


@dataclass(frozen=True)
class Markers:
    """The two hand-raised markers that key the incremental cache."""

    cache_version: str
    runner_fidelity_version: str


@dataclass(frozen=True)
class VerdictDiff:
    """Gremlins that differ between the base and the head run, each tuple sorted."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        """Whether both runs produced the same gremlins with the same verdicts."""
        return not (self.added or self.removed or self.changed)

    @property
    def changes_the_gremlin_set(self) -> bool:
        """Whether a gremlin exists in only one of the runs."""
        return bool(self.added or self.removed)


def guarded_changes(changed: Iterable[str], deleted: Iterable[str], guarded: Collection[str]) -> list[str]:
    """Return the changed repository paths that the cache-version guard covers, sorted.

    ``guarded`` comes from the guard's ``guarded_sources()`` on the head code, which cannot list a file the PR
    deleted, so every deleted package module counts as guarded.
    """
    deleted_modules = {path for path in deleted if path.startswith(PACKAGE_DIR) and path.endswith('.py')}
    return sorted({path for path in changed if path in guarded} | deleted_modules)


def verdicts_from_report(report: Mapping[str, Any], sample_root: Path) -> dict[str, str]:
    """Map each gremlin in a pytest-gremlins JSON report to its verdict.

    A gremlin is named by its path inside the sample, line, operator and description rather than its id: the id
    numbers gremlins within a file, so one added gremlin would renumber every later one. Gremlins that share all
    four get ``#2``, ``#3``... in report order.
    """
    verdicts: dict[str, str] = {}
    seen: Counter[str] = Counter()
    for entry in report['results']:
        relative_path = Path(entry['file_path']).relative_to(sample_root).as_posix()
        name = f'{relative_path}:{entry["line_number"]} {entry["operator"]}: {entry["description"]}'
        seen[name] += 1
        verdicts[name if seen[name] == 1 else f'{name} #{seen[name]}'] = entry['status']
    return verdicts


def compare_verdicts(base: Mapping[str, str], head: Mapping[str, str]) -> VerdictDiff:
    """Return the gremlins only one run has, and the shared gremlins whose verdict differs."""
    return VerdictDiff(
        added=tuple(sorted(head.keys() - base.keys())),
        removed=tuple(sorted(base.keys() - head.keys())),
        changed=tuple(
            f'{gremlin}: {base[gremlin]} -> {head[gremlin]}'
            for gremlin in sorted(base.keys() & head.keys())
            if base[gremlin] != head[gremlin]
        ),
    )


def _describe(diff: VerdictDiff) -> str:
    lines = [
        *(f'added: {gremlin}' for gremlin in diff.added),
        *(f'removed: {gremlin}' for gremlin in diff.removed),
        *(f'changed: {change}' for change in diff.changed),
    ]
    advice = CACHE_VERSION_ADVICE if diff.changes_the_gremlin_set else RUNNER_FIDELITY_ADVICE
    return '\n'.join(
        [
            'Gremlin verdicts on the sample project changed, but neither cache marker was raised, so users with '
            'a warm cache would keep the old verdicts:',
            *lines,
            advice,
        ]
    )


def check_verdicts(
    base: Mapping[str, str], head: Mapping[str, str], base_markers: Markers, head_markers: Markers
) -> str | None:
    """Return why the head code fails the check, or None when it passes.

    The check passes when every gremlin keeps its verdict, or when a cache marker was raised between base and
    head, which throws every cached verdict away.
    """
    diff = compare_verdicts(base, head)
    if diff.is_empty or base_markers != head_markers:
        return None
    return _describe(diff)
