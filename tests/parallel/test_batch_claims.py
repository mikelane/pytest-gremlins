"""No user-facing text may claim that batching reduces subprocesses (#733)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.parallel import persistent_pool

PARALLEL_DOC = (Path(__file__).resolve().parents[2] / 'docs' / 'api' / 'parallel.md').read_text(encoding='utf-8')


@pytest.mark.small
class DescribeParallelDocPerformanceComparison:
    def it_does_not_list_batch_mode_as_one_subprocess_per_batch(self) -> None:
        assert '| Batch | 1 per batch |' not in PARALLEL_DOC

    def it_does_not_claim_batch_timings_from_fewer_subprocesses(self) -> None:
        assert 'Batch (size=10):      100 x 600ms = 60 seconds' not in PARALLEL_DOC

    def it_does_not_claim_an_80x_speedup_from_batching(self) -> None:
        assert 'Speedup: 80x' not in PARALLEL_DOC


@pytest.mark.small
class DescribeParallelDocPersistentPoolExample:
    def it_does_not_call_submit_batch_even_faster(self) -> None:
        assert 'submit batches (even faster)' not in PARALLEL_DOC

    def it_does_not_claim_a_25x_subprocess_overhead_reduction(self) -> None:
        assert '**25x reduction**' not in PARALLEL_DOC


@pytest.mark.small
class DescribePersistentPoolDocstrings:
    def it_does_not_claim_reduced_subprocess_overhead_in_the_module_docstring(self) -> None:
        assert 'reduced subprocess overhead' not in (persistent_pool.__doc__ or '')

    def it_does_not_claim_the_pool_avoids_a_subprocess_per_gremlin(self) -> None:
        assert 'spawns a new subprocess per gremlin' not in (persistent_pool.PersistentWorkerPool.__doc__ or '')
