"""Fail a PR whose code changes a gremlin verdict without raising a cache version (#876).

The incremental cache keeps a verdict until ``CACHE_VERSION`` or ``RUNNER_FIDELITY_VERSION`` changes. The CI
``Verdict Change Check`` job runs pytest-gremlins on a fixed sample project with the base and the head code and
compares the per-gremlin verdicts:

    python scripts/check_verdict_change.py guarded-changes <base-sha>   # changed paths the guard covers
    python scripts/check_verdict_change.py run --out head.json          # verdicts and markers of this install
    python scripts/check_verdict_change.py compare base.json head.json  # exit 1 on a change without a bump

``compare`` exits 1 when a verdict changed and neither marker was raised, naming every changed gremlin and the
marker to raise. It also exits 1 when neither run produced a gremlin or a marker was lowered: markers only go up.
``run`` exits 2 when pytest-gremlins wrote no report or the report has no results.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

PACKAGE_DIR = 'src/pytest_gremlins/'
REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = 'tests/cache/test_cache_version_guard.py'
GUARD_MODULE = REPO_ROOT / GUARD_PATH
SAMPLE_DIR = REPO_ROOT / 'tests' / 'fixtures' / 'verdict_sample'
REPORT_PATH = Path('coverage') / 'gremlins' / 'gremlins.json'
GIT = shutil.which('git') or 'git'
EXIT_VERDICT_CHANGED = 1
EXIT_NO_REPORT = 2

CACHE_VERSION_ADVICE = (
    'The set of gremlins changed, so the change alters what gets mutated: raise CACHE_VERSION in '
    'src/pytest_gremlins/cache/versions.py.'
)
RUNNER_FIDELITY_ADVICE = (
    'Only verdicts changed, so the change alters test execution or the outcome-to-verdict mapping: raise '
    'RUNNER_FIDELITY_VERSION in src/pytest_gremlins/cache/incremental.py. If it alters what gets mutated '
    'instead, raise CACHE_VERSION in src/pytest_gremlins/cache/versions.py.'
)


NO_GREMLINS_MESSAGE = (
    'Neither run produced a gremlin on the sample project, so there are no verdicts to compare. Check that the '
    'sample in tests/fixtures/verdict_sample/ still has mutable code and that pytest-gremlins finds it.'
)
LOWERED_MARKER_MESSAGE = (
    'A cache marker was lowered ({lowered}). Markers only go up: lowering one revives verdicts that an older '
    'release cached. Restore the base value or raise it.'
)


@dataclass(frozen=True)
class Markers:
    """The two hand-raised markers that key the incremental cache."""

    cache_version: str
    runner_fidelity_version: str

    def lowered_from(self, base: Markers) -> list[str]:
        """Name each marker that is lower here than in ``base``."""
        lowered = []
        if _rank(self.cache_version) < _rank(base.cache_version):
            lowered.append('CACHE_VERSION')
        if _rank(self.runner_fidelity_version) < _rank(base.runner_fidelity_version):
            lowered.append('RUNNER_FIDELITY_VERSION')
        return lowered


def _rank(marker: str) -> int:
    """Order a marker by the number in it: ``7`` is 7 and ``rf21`` is 21."""
    return int(re.sub(r'\D', '', marker))


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
    deleted, so every deleted package module counts as guarded. An edit to the guard file itself counts too: the
    same PR may add a module to ``EXCLUDED_FROM_GUARD`` and change it, which the head's guard set no longer lists.
    """
    deleted_modules = {path for path in deleted if path.startswith(PACKAGE_DIR) and path.endswith('.py')}
    guarded_paths = {path for path in changed if path in guarded or path == GUARD_PATH}
    return sorted(guarded_paths | deleted_modules)


def verdicts_from_report(report: Mapping[str, Any], sample_root: Path) -> dict[str, str]:
    """Map each gremlin in a pytest-gremlins JSON report to its verdict.

    A gremlin is named by its path inside the sample, line, operator and description rather than its id: the id
    numbers gremlins within a file, so one added gremlin would renumber every later one. Gremlins that share all
    four get ``#2``, ``#3``... in report order.
    """
    verdicts: dict[str, str] = {}
    seen: Counter[str] = Counter()
    for entry in report['results']:
        relative_path = Path(entry['file_path']).resolve().relative_to(sample_root.resolve()).as_posix()
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
    head, which throws every cached verdict away. It fails when neither run produced a gremlin, or when a marker
    was lowered.
    """
    if not base and not head:
        return NO_GREMLINS_MESSAGE
    lowered = head_markers.lowered_from(base_markers)
    if lowered:
        return LOWERED_MARKER_MESSAGE.format(lowered=', '.join(lowered))
    diff = compare_verdicts(base, head)
    if diff.is_empty or base_markers != head_markers:
        return None
    return _describe(diff)


def guarded_repo_paths() -> set[str]:
    """Return the repository paths of the files the cache-version guard hashes, from its own file-set function."""
    spec = importlib.util.spec_from_file_location('cache_version_guard', GUARD_MODULE)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load the cache-version guard from {GUARD_MODULE}')
    guard = importlib.util.module_from_spec(spec)
    # The guard's dataclasses look their module up in sys.modules while it executes.
    sys.modules[spec.name] = guard
    spec.loader.exec_module(guard)
    return {source.relative_to(REPO_ROOT).as_posix() for source in guard.guarded_sources()}


def _git_diff_names(base_ref: str, *filters: str) -> list[str]:
    completed = subprocess.run(
        [GIT, 'diff', '--name-only', '--no-renames', *filters, base_ref, 'HEAD'],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.splitlines()


def _installed_markers() -> Markers:
    from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION  # noqa: PLC0415
    from pytest_gremlins.cache.versions import CACHE_VERSION  # noqa: PLC0415

    return Markers(cache_version=str(CACHE_VERSION), runner_fidelity_version=str(RUNNER_FIDELITY_VERSION))


def _run_sample(sample: Path, workdir: Path) -> dict[str, str] | None:
    shutil.rmtree(workdir, ignore_errors=True)
    shutil.copytree(sample, workdir)
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '--gremlins'], cwd=workdir, capture_output=True, text=True, check=False
    )
    report_file = workdir / REPORT_PATH
    if not report_file.is_file():
        print(completed.stdout, completed.stderr, sep='\n')
        return None
    return verdicts_from_report(json.loads(report_file.read_text(encoding='utf-8')), workdir)


def _guarded_changes_command(args: argparse.Namespace) -> int:
    changed = _git_diff_names(args.base_ref)
    deleted = _git_diff_names(args.base_ref, '--diff-filter=D')
    for path in guarded_changes(changed, deleted, guarded_repo_paths()):
        print(path)
    return 0


def _run_command(args: argparse.Namespace) -> int:
    verdicts = _run_sample(args.sample, args.workdir)
    if not verdicts:
        print(f'pytest-gremlins wrote no gremlin results for the sample at {args.sample}', file=sys.stderr)
        return EXIT_NO_REPORT
    markers = _installed_markers()
    run = {
        'cache_version': markers.cache_version,
        'runner_fidelity_version': markers.runner_fidelity_version,
        'verdicts': verdicts,
    }
    args.out.write_text(json.dumps(run, indent=2, sort_keys=True), encoding='utf-8')
    return 0


def _load_run(path: Path) -> tuple[dict[str, str], Markers]:
    run = json.loads(path.read_text(encoding='utf-8'))
    markers = Markers(cache_version=run['cache_version'], runner_fidelity_version=run['runner_fidelity_version'])
    return run['verdicts'], markers


def _compare_command(args: argparse.Namespace) -> int:
    base_verdicts, base_markers = _load_run(args.base)
    head_verdicts, head_markers = _load_run(args.head)
    failure = check_verdicts(base_verdicts, head_verdicts, base_markers, head_markers)
    if failure is not None:
        print(failure)
        return EXIT_VERDICT_CHANGED
    print(f'{len(head_verdicts)} sample gremlins checked: no verdict changed, or a cache marker was raised.')
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(required=True)

    guarded = commands.add_parser('guarded-changes', help='print the changed paths the cache-version guard covers')
    guarded.add_argument('base_ref', help='the commit to diff HEAD against')
    guarded.set_defaults(handler=_guarded_changes_command)

    run = commands.add_parser('run', help='run pytest-gremlins on the sample and record its verdicts')
    run.add_argument('--out', type=Path, required=True, help='where to write the verdicts and markers')
    run.add_argument('--sample', type=Path, default=SAMPLE_DIR, help='the sample project to copy')
    run.add_argument(
        '--workdir',
        type=Path,
        default=Path(tempfile.gettempdir()) / 'pytest-gremlins-verdict-sample',
        help='where to copy the sample; reuse it for base and head so gremlin paths match',
    )
    run.set_defaults(handler=_run_command)

    compare = commands.add_parser('compare', help='fail when a verdict changed without a cache-marker bump')
    compare.add_argument('base', type=Path, help='the run file from the base code')
    compare.add_argument('head', type=Path, help='the run file from the head code')
    compare.set_defaults(handler=_compare_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand and return its exit code."""
    args = _parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == '__main__':
    sys.exit(main())
