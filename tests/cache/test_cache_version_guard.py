"""Changing verdict-affecting source forces a decision about the cache markers (#867).

The recorded digest below covers the code that decides what a cached verdict means. When it no longer
matches, the author decides whether the change can alter a verdict for the same source and tests.

Two markers share the digest, each owning part of the hashed paths:

- ``RUNNER_FIDELITY_VERSION`` owns test execution and the mapping from test outcome to verdict:
  ``parallel/`` and ``control_run.py``.
- ``CACHE_VERSION`` owns what gets mutated: ``operators/`` and ``instrumentation/``.

``plugin.py`` wires both, so a change there raises whichever marker matches what it changed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION
from pytest_gremlins.cache.versions import CACHE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'pytest_gremlins'
VERDICT_AFFECTING_DIRECTORIES = ('operators', 'instrumentation', 'parallel')
VERDICT_AFFECTING_FILES = ('plugin.py', 'control_run.py')

RECORDED_CACHE_VERSION = 1
RECORDED_RUNNER_FIDELITY_VERSION = 'rf19'
RECORDED_DIGEST = '249d5403fda96844f56baf0678a47a433360fe706480d54906e42217845073fc'  # pragma: allowlist secret


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
