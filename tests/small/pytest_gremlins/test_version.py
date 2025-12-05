"""Tests for package version and basic imports."""

from __future__ import annotations

import re

import pytest

from pytest_gremlins import __version__


@pytest.mark.small
def test_version_is_string():
    assert isinstance(__version__, str)


@pytest.mark.small
def test_version_follows_semver_pattern():
    # Match semver with optional prerelease (e.g., 0.1.0-alpha.1)
    semver_pattern = r'^\d+\.\d+\.\d+(-[a-zA-Z]+\.\d+)?$'
    assert re.match(semver_pattern, __version__), f'Version {__version__} does not match semver pattern'
