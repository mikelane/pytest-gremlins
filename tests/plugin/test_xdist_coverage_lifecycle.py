"""Tests for PRIVATE + xdist coverage lifecycle.

When running with xdist in PRIVATE mode:

Controller side:
- pytest_configure_node: injects gremlins_tmpdir and gremlins_source_paths
  into node.workerinput so workers can create their own Coverage instances.

Worker side:
- pytest_sessionstart: reads workerinput, creates Coverage with unique
  data_suffix=worker_id, stores on GremlinSession.private_coverage.
- pytest_runtestloop: starts/stops private coverage (same as non-xdist PRIVATE).

Controller pytest_sessionfinish:
- Combines all worker .coverage files from the shared tmpdir before reading
  coverage data.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pytest_gremlins.plugin import (
    CoverageMode,
    GremlinSession,
    _set_session,
    pytest_configure_node,
)


@pytest.mark.small
class DescribeConfigureNode:
    """pytest_configure_node injects gremlins metadata into node.workerinput."""

    def it_injects_tmpdir_into_workerinput(self, tmp_path: Path) -> None:
        """Controller injects gremlins_tmpdir into node.workerinput."""
        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        gs.gremlins_tmpdir = str(tmp_path)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        node.workerinput = {}

        pytest_configure_node(node=node)

        assert 'gremlins_tmpdir' in node.workerinput
        assert node.workerinput['gremlins_tmpdir'] == str(tmp_path)

    def it_skips_when_session_disabled(self) -> None:
        """No injection when GremlinSession is disabled."""
        gs = GremlinSession(enabled=False)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        node.workerinput = {}

        pytest_configure_node(node=node)

        assert 'gremlins_tmpdir' not in node.workerinput

    def it_skips_when_no_session(self) -> None:
        """No injection when no GremlinSession exists."""
        _set_session(None)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        node.workerinput = {}

        pytest_configure_node(node=node)

        assert 'gremlins_tmpdir' not in node.workerinput

    def it_skips_in_piggyback_mode(self, tmp_path: Path) -> None:
        """No injection in PIGGYBACK mode - workers use pytest-cov's coverage."""
        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PIGGYBACK)
        gs.gremlins_tmpdir = str(tmp_path)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        node.workerinput = {}

        pytest_configure_node(node=node)

        assert 'gremlins_tmpdir' not in node.workerinput


@pytest.mark.medium
class DescribeConfigureNodeFileIO:
    """Filesystem tests for pytest_configure_node — require real directory creation."""

    def it_injects_different_tmpdir_ruling_out_hardcoding(self, tmp_path: Path) -> None:
        """Different tmpdir path is injected into workerinput - rules out hardcoding."""
        other_path = tmp_path / 'subdir'
        other_path.mkdir()

        gs = GremlinSession(enabled=True, coverage_mode=CoverageMode.PRIVATE)
        gs.gremlins_tmpdir = str(other_path)
        _set_session(gs)

        node = MagicMock()  # xdist worker node: Protocol type, spec= not applicable; bare-mock: ok
        node.workerinput = {}

        pytest_configure_node(node=node)

        assert node.workerinput['gremlins_tmpdir'] == str(other_path)


@pytest.mark.small
class DescribeGremlinSessionTmpdir:
    """GremlinSession has a gremlins_tmpdir field for shared coverage data."""

    def it_initializes_gremlins_tmpdir_as_none(self) -> None:
        """GremlinSession.gremlins_tmpdir defaults to None."""
        gs = GremlinSession()
        assert gs.gremlins_tmpdir is None

    def it_gremlins_tmpdir_can_be_set(self) -> None:
        """GremlinSession.gremlins_tmpdir can be set to a path string."""
        gs = GremlinSession(gremlins_tmpdir='/tmp/gremlins_test')  # noqa: S108
        assert gs.gremlins_tmpdir == '/tmp/gremlins_test'  # noqa: S108

    def it_stores_distinct_tmpdir_values_ruling_out_hardcoding(self) -> None:
        """Different tmpdir values produce different results - rules out hardcoding."""
        gs_a = GremlinSession(gremlins_tmpdir='/tmp/a')  # noqa: S108
        gs_b = GremlinSession(gremlins_tmpdir='/tmp/b')  # noqa: S108
        assert gs_a.gremlins_tmpdir != gs_b.gremlins_tmpdir
