"""End-to-end pytester tests for ``--gremlin-explain``.

Runs ``pytest --gremlins --gremlin-explain=<id>`` against a minimal project
and verifies that the diagnostic banner and per-set breakdown reach stdout,
that the mutation loop is short-circuited, and that pytest exits cleanly.
Drift detection itself is exercised by the unit tests in
``test_gremlin_explain.py``.
"""

from __future__ import annotations

import re

import pytest


def _write_project(pytester: pytest.Pytester) -> None:
    """Write a tiny target module plus one test into the pytester tmpdir."""
    pytester.makepyfile(
        target=("def classify(value: int) -> str:\n    if value == 0:\n        return 'zero'\n    return 'nonzero'\n"),
    )
    pytester.makepyfile(
        test_target=(
            'import pytest\n'
            'from target import classify\n'
            '\n'
            '@pytest.mark.small\n'
            'def test_zero_case():\n'
            "    assert classify(0) == 'zero'\n"
        ),
    )
    pytester.makepyprojecttoml(
        """
[tool.pytest-gremlins]
paths = ["target.py"]
"""
    )
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: fast unit tests')


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(m.name in ('small', 'medium', 'large') for m in item.iter_markers()):
            item.add_marker(pytest.mark.small)
"""
    )


_GREMLIN_PROGRESS_RE = re.compile(r'Gremlin \d+/\d+: (\S+)')


def _discover_gremlin_id(pytester: pytest.Pytester) -> str:
    """Run gremlins once and extract a real gremlin id from the progress log.

    The per-gremlin progress printer emits a line of the form
    ``Gremlin 1/N: <gremlin_id> - ...``. Matching it sidesteps any assumption
    about where the JSON report lands and keeps the test tied to user-visible
    output rather than internal file layouts.
    """
    bootstrap = pytester.runpytest('-p', 'pytest_gremlins', '--gremlins')
    match = _GREMLIN_PROGRESS_RE.search(bootstrap.stdout.str())
    if not match:
        pytest.skip(
            'Could not discover a gremlin id from the progress log; '
            'operator registry may have produced zero gremlins in this environment.',
        )
    return match.group(1)


@pytest.mark.medium
class DescribeGremlinExplainPytester:
    """End-to-end checks for the --gremlin-explain diagnostic."""

    def it_emits_diagnostic_and_short_circuits_mutation_loop(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)
        gremlin_id = _discover_gremlin_id(pytester)

        result = pytester.runpytest(
            '-p',
            'pytest_gremlins',
            '--gremlins',
            f'--gremlin-explain={gremlin_id}',
        )

        output = result.stdout.str()
        # Diagnostic banner identifies the exact gremlin requested.
        assert f'--gremlin-explain: diagnostic for {gremlin_id}' in output, output
        # Per-set breakdown must be structured (name + count + colon), not just a
        # bare word — a regression that dropped the counts would pass a plain
        # substring check.
        assert re.search(r'Covering set \(\d+ test\(s\)\):', output), output
        assert re.search(r'Selected list \(\d+ test\(s\)\):', output), output
        # Mutation loop is short-circuited: no per-gremlin progress after the diagnostic.
        post_explain = output.split('--gremlin-explain: diagnostic for', 1)[-1]
        assert 'Gremlin 1/' not in post_explain, post_explain
        # Pytest exits cleanly so the user's own tests still count.
        assert result.ret == 0, output

    def it_reports_unknown_gremlin_id(self, pytester: pytest.Pytester) -> None:
        _write_project(pytester)
        # Prove the rest of the suite is healthy before we ask for an unknown id.
        _discover_gremlin_id(pytester)

        result = pytester.runpytest(
            '-p',
            'pytest_gremlins',
            '--gremlins',
            '--gremlin-explain=no_such_gremlin_id',
        )

        output = result.stdout.str()
        # Assert the exact banner shape: both the "no gremlin with id" phrase and
        # the offending id (``repr``-quoted by the production code) must appear
        # on the same line. Two separate ``in`` checks could pass even if the id
        # appeared only in an unrelated pytest frame.
        assert "--gremlin-explain: no gremlin with id 'no_such_gremlin_id' in this session." in output, output
        # None of the per-set breakdown should be emitted for an unknown id.
        assert 'Covering set' not in output, output
        assert 'Selected list' not in output, output
        # Pytest still exits cleanly: unknown id short-circuits mutation but
        # never fails the session on the user's behalf.
        assert result.ret == 0, output
