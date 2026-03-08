"""Medium pytester E2E tests for pardoning features.

Covers the full pardoning workflow end-to-end: the ``# gremlin: pardon[...]``
pragma, threshold flags (--max-pardons, --gremlin-max-pardons-pct),
--strict-pardons, --gremlin-audit-pardons, and --gremlin-batch with pardons.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def pardoned_project(pytester_with_markers: pytest.Pytester) -> pytest.Pytester:
    """Pytester project with one pardoned arithmetic mutation."""
    pytester_with_markers.makepyfile(
        src_module="""
def add(a, b):
    return a + b  # gremlin: pardon[equivalent] addition is equivalent here
""",
    )
    pytester_with_markers.makepyfile(
        test_src="""
from src_module import add

def test_add():
    assert add(2, 3) == 5
""",
    )
    return pytester_with_markers


@pytest.mark.medium
class DescribeE2EPardoning:
    def it_pardoned_gremlin_reports_pardoned_status(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest('--gremlins', '--gremlin-targets=src_module.py')

        assert 'Pardoned:' in result.stdout.str()

    def it_pardoned_gremlin_excluded_from_score(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest('--gremlins', '--gremlin-targets=src_module.py')

        assert result.ret == 0

    def it_max_pardons_fails_when_exceeded(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--max-pardons=0',
        )

        assert result.ret != 0
        assert 'Max pardons exceeded' in result.stdout.str()

    def it_max_pardons_passes_when_within_limit(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--max-pardons=5',
        )

        assert result.ret == 0

    def it_max_pardons_pct_fails_when_exceeded(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--gremlin-max-pardons-pct=0.0',
        )

        assert result.ret != 0
        assert 'Max pardons exceeded' in result.stdout.str()

    def it_strict_pardons_fails_with_any_pardon(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--strict-pardons',
        )

        assert result.ret != 0
        assert '--strict-pardons' in result.stderr.str()

    def it_audit_pardons_lists_pardon_details(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--gremlin-audit-pardons',
        )

        assert 'equivalent' in result.stdout.str()

    def it_batch_mode_pardons(self, pardoned_project: pytest.Pytester) -> None:
        result = pardoned_project.runpytest(
            '--gremlins',
            '--gremlin-targets=src_module.py',
            '--gremlin-batch',
        )

        assert 'Pardoned:' in result.stdout.str()
