"""Shared fixtures for integration tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ATTRS_COMMIT_SHA = 'bd2446d77736a164b59b268a3792ed3e4bfba088'  # pragma: allowlist secret
ATTRS_CHECKOUT_DEFAULT = '/tmp/attrs-checkout'  # noqa: S108


@pytest.fixture(scope='module')
def attrs_checkout() -> Path:
    """Path to the attrs source checkout.

    In CI, the checkout is cached at /tmp/attrs-checkout.
    For local runs, set ATTRS_CHECKOUT env var or skip.
    """
    checkout_path = Path(os.environ.get('ATTRS_CHECKOUT', ATTRS_CHECKOUT_DEFAULT))
    if not checkout_path.exists():
        pytest.skip(f'attrs checkout not found at {checkout_path}. Set ATTRS_CHECKOUT env var or run in CI.')
    return checkout_path


@pytest.fixture(scope='module')
def attrs_venv(attrs_checkout: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Temporary venv with attrs and gremlins installed."""
    venv_dir = tmp_path_factory.mktemp('attrs-venv')
    subprocess.run(['uv', 'venv', str(venv_dir), '--quiet'], check=True)  # noqa: S607

    python = str(venv_dir / 'bin' / 'python')
    gremlins_src = str(Path(__file__).parents[2])

    # Install attrs from the checkout + gremlins from source + test deps
    subprocess.run(
        [  # noqa: S607
            'uv',
            'pip',
            'install',
            '--python',
            python,
            '-e',
            str(attrs_checkout),
            '-e',
            gremlins_src,
            'pytest',
            'hypothesis',
            '-q',
        ],
        check=True,
        capture_output=True,
    )
    return venv_dir
