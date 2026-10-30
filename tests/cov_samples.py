"""Shared project sample and result checks for the pytest-cov loader tests (refs #654).

Every gremlin run of the strong test zaps every comparison gremlin of ``classify``, so a clean run has
no errors and no survivors. An error or a survivor means the gremlin runs could not load pytest-cov the
way the session did.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rerun_samples import (
    SAMPLE,
    verdicts,
)

if TYPE_CHECKING:
    import pytest

STRONG_TEST = """
from sample import classify


def test_boundary():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

SESSION_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'gremlins')


def write_project(pytester: pytest.Pytester) -> None:
    """Write the sample module and the strong test that zaps all of its comparison gremlins."""
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=STRONG_TEST)


def assert_gremlins_ran_cleanly(result: pytest.RunResult) -> None:
    """Assert pytest-cov loaded once in every gremlin run and every gremlin was zapped."""
    output = result.stdout.str() + result.stderr.str()
    assert 'unrecognized arguments' not in output
    assert 'already registered' not in output
    counted = verdicts(output)
    assert counted['Error'] == 0
    assert counted['Survived'] == 0
    assert counted['Zapped'] > 0
