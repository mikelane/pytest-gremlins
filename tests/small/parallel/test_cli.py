"""Tests for parallel execution CLI options.

These tests verify the CLI option parsing and configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import pytest


class TestParallelCLIOptions:
    """Tests for parallel CLI option parsing via pytest."""

    def test_gremlin_parallel_option_exists(self, pytester: pytest.Pytester) -> None:
        """--gremlin-parallel option is available."""
        result = pytester.runpytest('--help')
        result.stdout.fnmatch_lines(['*--gremlin-parallel*'])

    def test_gremlin_workers_option_exists(self, pytester: pytest.Pytester) -> None:
        """--gremlin-workers option is available."""
        result = pytester.runpytest('--help')
        result.stdout.fnmatch_lines(['*--gremlin-workers*'])

    def test_parallel_disabled_by_default(self, pytester: pytest.Pytester) -> None:
        """Parallel execution is disabled by default."""
        pytester.makepyfile(
            test_sample="""
            def test_pass():
                assert True
            """
        )
        # Run without --gremlins flag - should work with no errors
        result = pytester.runpytest('-v')
        assert result.ret == 0

    def test_workers_accepts_integer(self, pytester: pytest.Pytester) -> None:
        """--gremlin-workers accepts an integer value."""
        pytester.makepyfile(
            test_sample="""
            def test_pass():
                assert True
            """
        )
        # Should not fail from invalid option
        result = pytester.runpytest('--gremlin-workers=4', '-v')
        assert result.ret == 0
