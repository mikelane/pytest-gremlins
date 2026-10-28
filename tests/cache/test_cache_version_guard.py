"""Changing verdict-affecting source forces a decision about ``CACHE_VERSION`` (#867).

The recorded digest below covers the code that decides what a cached verdict means. When it no longer
matches, the author decides whether the change can alter a verdict for the same source and tests.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pytest_gremlins.cache.versions import CACHE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'pytest_gremlins'
VERDICT_AFFECTING_DIRECTORIES = ('operators', 'instrumentation')
VERDICT_AFFECTING_FILES = ('plugin.py', 'control_run.py', 'rerun_options.py')

RECORDED_CACHE_VERSION = 1
RECORDED_DIGEST = 'placeholder'


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
            'source and tests (operators, instrumentation, how verdicts are decided). If it can, raise '
            'CACHE_VERSION in src/pytest_gremlins/cache/versions.py. Either way, update RECORDED_DIGEST in '
            f"this file to '{current}' (and RECORDED_CACHE_VERSION if you raised the version)."
        )

    def it_records_the_current_cache_version(self) -> None:
        assert RECORDED_CACHE_VERSION == CACHE_VERSION, (
            f'CACHE_VERSION is {CACHE_VERSION} but the guard recorded {RECORDED_CACHE_VERSION}. '
            'Update RECORDED_CACHE_VERSION and RECORDED_DIGEST together.'
        )
