"""Changing package source forces a decision about the cache markers (#867).

The recorded digest below covers every ``*.py`` file under ``src/pytest_gremlins/`` except the paths named in
``EXCLUDED_FROM_GUARD``. A new file is guarded the moment it exists; nothing has to be added to a list. When the
digest no longer matches, the author decides whether the change can alter a verdict, or which gremlins exist,
for the same source and tests:

- ``CACHE_VERSION`` owns what gets mutated: ``operators/``, ``instrumentation/`` and anything else that changes
  which gremlins exist.
- ``RUNNER_FIDELITY_VERSION`` owns test execution and the mapping from test outcome to verdict: ``parallel/``,
  ``control_run.py`` and the code that shapes the gremlin subprocess command line.
- A change that cannot alter any verdict leaves both markers alone; re-record the digest.
- A file that can never influence a verdict goes into ``EXCLUDED_FROM_GUARD`` with a one-line reason, which review
  checks. When unsure, leave the file guarded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil

import pytest

from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION
from pytest_gremlins.cache.versions import CACHE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'pytest_gremlins'

# Keys are package-relative POSIX paths: a file, or a directory prefix ending in "/".
# Only renderers that run after every verdict is decided belong here. Nothing on the verdict path imports them:
# the parallel executors and plugin.py import only reporting/results.py (GremlinResultStatus), and
# reporting/score.py, reporting/types.py and reporting/__init__.py stay guarded.
EXCLUDED_FROM_GUARD: dict[str, str] = {
    '__init__.py': 'Holds only __version__, which cz bump rewrites each release; decides no verdict.',
    'reporting/console.py': 'Formats finished results for the terminal; decides no verdict.',
    'reporting/diff.py': 'Renders the original-versus-mutated diff shown in reports; decides no verdict.',
    'reporting/history.py': 'Persists per-run scores for trend charts after the run; decides no verdict.',
    'reporting/html.py': 'Renders finished results as an HTML report; decides no verdict.',
    'reporting/json_reporter.py': 'Serialises finished results as a JSON report; decides no verdict.',
    'reporting/sonarqube_export.py': 'Exports finished results in SonarQube format; decides no verdict.',
    'reporting/stryker_export.py': 'Exports finished results in Stryker format; decides no verdict.',
}

RECORDED_CACHE_VERSION = 1
RECORDED_RUNNER_FIDELITY_VERSION = 'rf20'
RECORDED_DIGEST = '145d5f12899c0d39bd29a8af2467eee6eb85a7cc907edd90713377f4fb4d1a57'  # pragma: allowlist secret


def _is_excluded(relative_path: str) -> bool:
    return any(
        relative_path == excluded or (excluded.endswith('/') and relative_path.startswith(excluded))
        for excluded in EXCLUDED_FROM_GUARD
    )


def guarded_sources() -> list[Path]:
    """Return the package sources whose content the cache-version guard hashes, in digest order.

    That is every ``*.py`` file under the package except the paths in ``EXCLUDED_FROM_GUARD``, sorted by
    package-relative POSIX path. The release-time check (#877) and the CI verdict-diff job (#876) must call
    this function rather than keep their own list, so a file can never be guarded in one place and missed in
    another.
    """
    candidates = (
        (source, source.relative_to(PACKAGE_ROOT).as_posix())
        for source in PACKAGE_ROOT.rglob('*.py')
        if '__pycache__' not in source.parts
    )
    return [source for source, relative in sorted(candidates, key=lambda pair: pair[1]) if not _is_excluded(relative)]


def _guarded_digest() -> str:
    digest = hashlib.sha256()
    for source in guarded_sources():
        digest.update(source.relative_to(PACKAGE_ROOT).as_posix().encode())
        digest.update(b'\0')
        digest.update(source.read_bytes().replace(b'\r\n', b'\n'))
        digest.update(b'\0')
    return digest.hexdigest()


def _copy_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package_copy = tmp_path / 'pytest_gremlins'
    shutil.copytree(PACKAGE_ROOT, package_copy, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setitem(globals(), 'PACKAGE_ROOT', package_copy)
    return package_copy


@pytest.mark.medium
class DescribeCacheVersionGuard:
    """The recorded digest and ``CACHE_VERSION`` move together with the verdict-affecting source."""

    def it_matches_the_recorded_digest_of_guarded_source(self) -> None:
        current = _guarded_digest()

        assert current == RECORDED_DIGEST, (
            'Guarded package source changed. Decide whether the change can alter a verdict, or which gremlins '
            'exist, for the same source and tests. If it changes what gets mutated, raise CACHE_VERSION in '
            'src/pytest_gremlins/cache/versions.py. If it changes test execution or the outcome-to-verdict '
            'mapping, raise RUNNER_FIDELITY_VERSION in src/pytest_gremlins/cache/incremental.py. If neither, '
            'only re-record. Then update RECORDED_DIGEST in this file to '
            f"'{current}' (and RECORDED_CACHE_VERSION or RECORDED_RUNNER_FIDELITY_VERSION for the marker you "
            'raised). If the file can never influence a verdict, add it to EXCLUDED_FROM_GUARD with a reason '
            'instead.'
        )

    def it_records_the_current_cache_version(self) -> None:
        assert RECORDED_CACHE_VERSION == CACHE_VERSION, (
            f'CACHE_VERSION is {CACHE_VERSION} but the guard recorded {RECORDED_CACHE_VERSION}. '
            'Update RECORDED_CACHE_VERSION and RECORDED_DIGEST together.'
        )

    def it_records_the_current_runner_fidelity_version(self) -> None:
        assert RECORDED_RUNNER_FIDELITY_VERSION == RUNNER_FIDELITY_VERSION, (
            f'RUNNER_FIDELITY_VERSION is {RUNNER_FIDELITY_VERSION!r} but the guard recorded '
            f'{RECORDED_RUNNER_FIDELITY_VERSION!r}. '
            'Update RECORDED_RUNNER_FIDELITY_VERSION and RECORDED_DIGEST together.'
        )

    @pytest.mark.parametrize(
        'guarded_file', ['node_id_args.py', 'rerun_options.py', 'config.py', 'gremlins_options.py']
    )
    def it_changes_the_digest_when_a_guarded_file_changes(
        self, guarded_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digest()

        target = package_copy / guarded_file
        target.write_text(target.read_text() + '\n_CHANGED = True\n')

        assert _guarded_digest() != before

    @pytest.mark.parametrize('new_file', ['brand_new_module.py', 'newpackage/deep/module.py'])
    def it_guards_a_new_source_file_without_any_list_edit(
        self, new_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digest()

        (package_copy / new_file).parent.mkdir(parents=True, exist_ok=True)
        (package_copy / new_file).write_text('VALUE = 1\n')

        assert _guarded_digest() != before

    @pytest.mark.parametrize('excluded_file', sorted(EXCLUDED_FROM_GUARD))
    def it_ignores_edits_to_an_excluded_file(
        self, excluded_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digest()

        target = package_copy / excluded_file
        target.write_text(target.read_text() + '\n_CHANGED = True\n')

        assert _guarded_digest() == before

    def it_keeps_the_digest_when_a_release_bump_rewrites_only_the_package_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digest()

        init_file = package_copy / '__init__.py'
        init_file.write_text(re.sub(r"__version__ = '[^']*'", "__version__ = '999.0.0'", init_file.read_text()))

        assert _guarded_digest() == before

    @pytest.mark.parametrize('excluded_path', sorted(EXCLUDED_FROM_GUARD))
    def it_names_only_existing_paths_in_the_exclusion_list(self, excluded_path: str) -> None:
        assert (PACKAGE_ROOT / excluded_path).exists(), (
            f'EXCLUDED_FROM_GUARD names {excluded_path!r}, which does not exist. Remove the stale exclusion.'
        )

    @pytest.mark.parametrize('excluded_path', sorted(EXCLUDED_FROM_GUARD))
    def it_gives_every_exclusion_a_reason(self, excluded_path: str) -> None:
        assert EXCLUDED_FROM_GUARD[excluded_path].strip(), f'{excluded_path!r} is excluded without a reason.'

    def it_excludes_nothing_that_the_verdict_path_imports(self) -> None:
        guarded = {source.relative_to(PACKAGE_ROOT).as_posix() for source in guarded_sources()}

        assert {'config.py', 'gremlins_options.py', 'plugin.py', 'reporting/results.py'} <= guarded
