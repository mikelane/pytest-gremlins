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

    def it_treats_piggyback_and_private_as_distinct_modes(self) -> None:
        """PIGGYBACK and PRIVATE are distinct values - rules out both returning same."""
        assert CoverageMode.PIGGYBACK != CoverageMode.PRIVATE


@pytest.mark.small
class DescribeDetectCoverageMode:
    """_detect_coverage_mode returns the correct mode based on plugin presence."""

    def it_returns_piggyback_when_cov_plugin_present(self) -> None:
        """Returns PIGGYBACK when '_cov' plugin is registered."""
        config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        config.pluginmanager.get_plugin.return_value = MagicMock()  # pytest-cov plugin: truthy filler; bare-mock: ok

        result = _detect_coverage_mode(config)

        config.pluginmanager.get_plugin.assert_called_once_with('_cov')
        assert result == CoverageMode.PIGGYBACK

    def it_returns_private_when_cov_plugin_absent(self) -> None:
        """Returns PRIVATE when '_cov' plugin returns None."""
        config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        config.pluginmanager.get_plugin.return_value = None

        result = _detect_coverage_mode(config)

        assert result == CoverageMode.PRIVATE

    def it_produces_different_results_for_piggyback_and_private(self) -> None:
        """Present vs absent plugin produces different modes - rules out hardcoding."""
        config_with_cov = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        config_with_cov.pluginmanager.get_plugin.return_value = MagicMock()  # truthy filler; bare-mock: ok

        config_without_cov = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        config_without_cov.pluginmanager.get_plugin.return_value = None

        mode_with = _detect_coverage_mode(config_with_cov)
        mode_without = _detect_coverage_mode(config_without_cov)

        assert mode_with != mode_without
