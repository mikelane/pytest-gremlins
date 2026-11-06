"""Leaving the pool on an error reports that error even when abandoning the workers fails (issue #976)."""

from __future__ import annotations

import pytest

from pytest_gremlins.parallel.pool import WorkerPool


class DescribeLeavingThePoolOnAnErrorWhenAbandoningFails:
    @pytest.mark.small
    def it_lets_the_original_error_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_abandon(_pool: WorkerPool) -> None:
            msg = 'cannot list the workers'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_abandon_workers', failing_abandon)

        with pytest.raises(KeyError, match='original'), WorkerPool(max_workers=1):
            raise KeyError('original')

    @pytest.mark.small
    def it_still_shuts_the_pool_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_abandon(_pool: WorkerPool) -> None:
            msg = 'cannot list the workers'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_abandon_workers', failing_abandon)
        pool = WorkerPool(max_workers=1)

        with pytest.raises(KeyError), pool:
            raise KeyError('original')

        assert pool._shutdown_called
