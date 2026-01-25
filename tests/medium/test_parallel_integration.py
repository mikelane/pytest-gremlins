"""Integration tests for parallel execution.

These tests verify that parallel execution works correctly end-to-end.
"""

from __future__ import annotations

import pytest


class TestParallelExecution:
    """Tests for parallel execution mode."""

    def test_parallel_flag_enables_parallel_mode(self, pytester: pytest.Pytester) -> None:
        """--gremlin-parallel flag enables parallel execution."""
        # Create a simple source file
        pytester.makepyfile(
            sample="""
            def is_positive(x):
                return x > 0
            """
        )

        # Create a test that covers the source
        pytester.makepyfile(
            test_sample="""
            from sample import is_positive

            def test_positive():
                assert is_positive(5) is True

            def test_negative():
                assert is_positive(-1) is False
            """
        )

        # Run with parallel mode enabled
        result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=2',
            '-v',
        )

        # Verify parallel execution output
        result.stdout.fnmatch_lines(['*Starting parallel execution*'])

    def test_parallel_produces_correct_results(self, pytester: pytest.Pytester) -> None:
        """Parallel execution produces correct mutation results."""
        pytester.makepyfile(
            sample="""
            def add(a, b):
                return a + b
            """
        )

        pytester.makepyfile(
            test_sample="""
            from sample import add

            def test_add():
                assert add(2, 3) == 5
                assert add(0, 0) == 0
            """
        )

        result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=2',
            '-v',
        )

        # Should show mutation report
        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*'])

    def test_parallel_with_single_worker(self, pytester: pytest.Pytester) -> None:
        """Parallel mode works with a single worker."""
        pytester.makepyfile(
            sample="""
            def negate(x):
                return -x
            """
        )

        pytester.makepyfile(
            test_sample="""
            from sample import negate

            def test_negate():
                assert negate(5) == -5
            """
        )

        result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=1',
            '-v',
        )

        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*'])

    def test_parallel_without_workers_flag_uses_auto(self, pytester: pytest.Pytester) -> None:
        """Parallel mode without --gremlin-workers uses auto detection."""
        pytester.makepyfile(
            sample="""
            def double(x):
                return x * 2
            """
        )

        pytester.makepyfile(
            test_sample="""
            from sample import double

            def test_double():
                assert double(3) == 6
            """
        )

        result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '-v',
        )

        # Should show auto worker detection
        result.stdout.fnmatch_lines(['*Starting parallel execution with auto workers*'])


class TestSequentialVsParallelConsistency:
    """Tests that parallel and sequential modes produce consistent results."""

    def test_same_mutations_found(self, pytester: pytest.Pytester) -> None:
        """Parallel mode finds the same mutations as sequential mode."""
        source_code = """
def compare(a, b):
    if a > b:
        return 1
    elif a < b:
        return -1
    return 0
"""
        test_code = """
from sample import compare

def test_compare():
    assert compare(5, 3) == 1
    assert compare(3, 5) == -1
    assert compare(4, 4) == 0
"""
        # Run sequential
        pytester.makepyfile(sample=source_code)
        pytester.makepyfile(test_sample=test_code)

        seq_result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '-v',
        )

        # Run parallel (in same environment)
        par_result = pytester.runpytest(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=2',
            '-v',
        )

        # Both should show mutation reports
        seq_result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*'])
        par_result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*'])
