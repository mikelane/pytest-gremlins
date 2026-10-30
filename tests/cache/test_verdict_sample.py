"""The fixed sample project that the CI verdict-diff job runs pytest-gremlins on (#876).

The job compares per-gremlin verdicts for the base and head code. It only sees verdict changes the sample
exercises, so the sample has to keep at least one gremlin for every built-in operator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.instrumentation.transformer import (
    get_default_registry,
    transform_source,
)

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'verdict_sample'
SAMPLE_TARGET = SAMPLE_ROOT / 'sample.py'
# Read at import: small tests may not touch the filesystem.
SAMPLE_SOURCE = SAMPLE_TARGET.read_text(encoding='utf-8')


def _operators_with_a_gremlin() -> set[str]:
    gremlins, _ = transform_source(SAMPLE_SOURCE, str(SAMPLE_TARGET))
    return {gremlin.operator_name for gremlin in gremlins}


@pytest.mark.small
class DescribeVerdictSampleOperatorCoverage:
    @pytest.mark.parametrize('operator', sorted(get_default_registry().available()))
    def it_has_a_gremlin_for_every_built_in_operator(self, operator: str) -> None:
        assert operator in _operators_with_a_gremlin(), (
            f'The verdict sample at {SAMPLE_TARGET} has no {operator!r} gremlin. Add code that the {operator!r} '
            'operator mutates, so the CI verdict-diff job sees verdict changes for it.'
        )
