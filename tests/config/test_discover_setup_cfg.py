"""Tests for source path discovery from setup.cfg."""

from pathlib import Path

import pytest

from pytest_gremlins.config import discover_by_setup_cfg


@pytest.mark.medium
class DescribeDiscoverBySetupCfg:
    """Tests for discover_by_setup_cfg function."""

    def it_returns_empty_when_no_setup_cfg(self, tmp_path):
        result = discover_by_setup_cfg(tmp_path)

        assert result == []

    def it_discovers_packages_from_options(self, tmp_path):
        (tmp_path / 'setup.cfg').write_text('[options]\npackages = mypackage\n')
        (tmp_path / 'mypackage').mkdir()

        result = discover_by_setup_cfg(tmp_path)

        assert result == [Path('mypackage')]

    def it_discovers_find_where(self, tmp_path):
        (tmp_path / 'setup.cfg').write_text('[options.packages.find]\nwhere = src\n')
        (tmp_path / 'src').mkdir()

        result = discover_by_setup_cfg(tmp_path)

        assert result == [Path('src')]

    def it_filters_nonexistent_paths(self, tmp_path):
        (tmp_path / 'setup.cfg').write_text('[options]\npackages = missing_pkg\n')

        result = discover_by_setup_cfg(tmp_path)

        assert result == []

    def it_handles_malformed_setup_cfg_gracefully(self, tmp_path):
        (tmp_path / 'setup.cfg').write_text('\x00\x01\x02invalid\x00')

        result = discover_by_setup_cfg(tmp_path)

        assert result == []
