"""Changing verdict-affecting source forces a decision about the cache markers (#867).

The recorded digest below covers the code that decides what a cached verdict means. When it no longer
matches, the author decides whether the change can alter a verdict for the same source and tests.

Two markers share the digest, each owning part of the hashed paths:

- ``RUNNER_FIDELITY_VERSION`` owns test execution and the mapping from test outcome to verdict:
  ``parallel/``, ``control_run.py`` and the code that shapes the gremlin subprocess command line
  (``node_id_args.py``, which ``plugin.py`` pastes into the gremlin bootstrap, ``node_id_file.py`` and
  ``xdist_options.py``).
- ``CACHE_VERSION`` owns what gets mutated: ``operators/`` and ``instrumentation/``.

``plugin.py`` wires both, so a change there raises whichever marker matches what it changed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

import pytest

from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION
from pytest_gremlins.cache.versions import CACHE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'pytest_gremlins'
VERDICT_AFFECTING_DIRECTORIES = ('operators', 'instrumentation', 'parallel')
VERDICT_AFFECTING_FILES = (
    'plugin.py',
    'control_run.py',
    'node_id_args.py',
    'node_id_file.py',
    'xdist_options.py',
)

RECORDED_CACHE_VERSION = 1
RECORDED_RUNNER_FIDELITY_VERSION = 'rf19'
RECORDED_DIGEST = '50a27994c56c42891a464ee90670b26fe59faf8a3791e0bac66279d135a8465c'  # pragma: allowlist secret


def _verdict_affecting_sources() -> list[Path]:
    directory_sources = (
        source
        for directory in VERDICT_AFFECTING_DIRECTORIES
        for source in (PACKAGE_ROOT / directory).rglob('*.py')
        if '__pycache__' not in source.parts
    )
    file_sources = (PACKAGE_ROOT / name for name in VERDICT_AFFECTING_FILES)
    return sorted([*directory_sources, *file_sources], key=lambda source: source.relative_to(PACKAGE_ROOT).as_posix())


def _verdict_affecting_digest() -> str:
    digest = hashlib.sha256()
    for source in _verdict_affecting_sources():
        digest.update(source.relative_to(PACKAGE_ROOT).as_posix().encode())
        digest.update(b'\0')
        digest.update(source.read_bytes().replace(b'\r\n', b'\n'))
        digest.update(b'\0')
    return digest.hexdigest()


@pytest.mark.medium
class DescribeCacheVersionGuard:
    """The recorded digest and ``CACHE_VERSION`` move together with the verdict-affecting source."""

    def it_matches_the_recorded_digest_of_verdict_affecting_source(self) -> None:
        current = _verdict_affecting_digest()

        assert current == RECORDED_DIGEST, (
            'Verdict-affecting source changed. Decide whether the change can alter a verdict for the same '
            'source and tests. If it can, raise CACHE_VERSION in src/pytest_gremlins/cache/versions.py, or '
            'RUNNER_FIDELITY_VERSION in src/pytest_gremlins/cache/incremental.py if the change is in test '
            'execution. Then record the new digest: update RECORDED_DIGEST in this file to '
            f"'{current}' (and RECORDED_CACHE_VERSION or RECORDED_RUNNER_FIDELITY_VERSION for the marker you raised)."
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

    def it_changes_the_digest_when_the_embedded_node_id_args_source_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = tmp_path / 'pytest_gremlins'
        shutil.copytree(PACKAGE_ROOT, package_copy, ignore=shutil.ignore_patterns('__pycache__'))
        monkeypatch.setitem(globals(), 'PACKAGE_ROOT', package_copy)
        before = _verdict_affecting_digest()

        node_id_args = package_copy / 'node_id_args.py'
        node_id_args.write_text(node_id_args.read_text() + '\nNODE_IDS_FILE_OPTION = "--changed"\n')

        assert _verdict_affecting_digest() != before
