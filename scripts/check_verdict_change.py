"""Fail a PR whose code changes a gremlin verdict without raising a cache version (#876)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
