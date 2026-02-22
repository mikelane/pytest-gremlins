"""Tests for PIGGYBACK coverage mode detection and CoverageMode enum.

PIGGYBACK mode is active when pytest-cov (the '_cov' plugin) is present in
the plugin manager.  PRIVATE mode is used otherwise.

These tests verify:
- CoverageMode enum has PIGGYBACK and PRIVATE values
- _detect_coverage_mode returns PIGGYBACK when '_cov' plugin is registered
- _detect_coverage_mode returns PRIVATE when '_cov' plugin is absent
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytest_gremlins.plugin import (
    CoverageMode,
    _detect_coverage_mode,
)


@pytest.mark.small
class DescribeCoverageModeEnum:
    """CoverageMode enum has the expected members."""

    def it_has_piggyback_member(self) -> None:
        """CoverageMode.PIGGYBACK is a member of the enum."""
        assert CoverageMode.PIGGYBACK.name == 'PIGGYBACK'

    def it_has_private_member(self) -> None:
        """CoverageMode.PRIVATE is a member of the enum."""
        assert CoverageMode.PRIVATE.name == 'PRIVATE'

    def it_piggyback_and_private_are_distinct(self) -> None:
        """PIGGYBACK and PRIVATE are distinct values - rules out both returning same."""
        assert CoverageMode.PIGGYBACK != CoverageMode.PRIVATE


@pytest.mark.small
class DescribeDetectCoverageMode:
    """_detect_coverage_mode returns the correct mode based on plugin presence."""

    def it_returns_piggyback_when_cov_plugin_present(self) -> None:
        """Returns PIGGYBACK when '_cov' plugin is registered."""
        config = MagicMock()
        config.pluginmanager.get_plugin.return_value = MagicMock()

        result = _detect_coverage_mode(config)

        config.pluginmanager.get_plugin.assert_called_once_with('_cov')
        assert result == CoverageMode.PIGGYBACK

    def it_returns_private_when_cov_plugin_absent(self) -> None:
        """Returns PRIVATE when '_cov' plugin returns None."""
        config = MagicMock()
        config.pluginmanager.get_plugin.return_value = None

        result = _detect_coverage_mode(config)

        assert result == CoverageMode.PRIVATE

    def it_piggyback_and_private_produce_different_results(self) -> None:
        """Present vs absent plugin produces different modes - rules out hardcoding."""
        config_with_cov = MagicMock()
        config_with_cov.pluginmanager.get_plugin.return_value = MagicMock()

        config_without_cov = MagicMock()
        config_without_cov.pluginmanager.get_plugin.return_value = None

        mode_with = _detect_coverage_mode(config_with_cov)
        mode_without = _detect_coverage_mode(config_without_cov)

        assert mode_with != mode_without
