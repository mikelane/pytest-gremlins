"""Tests for the periodic flush policy that keeps cached results durable during a long run (issue #974)."""

from __future__ import annotations

import pytest

from pytest_gremlins.cache.periodic_flush import PeriodicFlusher


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.small
class DescribePeriodicFlusher:
    def it_does_not_flush_before_the_count_or_interval_is_reached(self) -> None:
        flushes: list[int] = []
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=3, every_seconds=10.0, clock=FakeClock())

        flusher.note_result()
        flusher.note_result()
        flusher.flush_if_due()

        assert flushes == []

    def it_flushes_once_the_result_count_is_reached(self) -> None:
        flushes: list[int] = []
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=3, every_seconds=10.0, clock=FakeClock())

        for _ in range(3):
            flusher.note_result()
        flusher.flush_if_due()

        assert flushes == [1]

    def it_restarts_the_count_after_a_flush(self) -> None:
        flushes: list[int] = []
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=2, every_seconds=10.0, clock=FakeClock())

        for _ in range(3):
            flusher.note_result()
            flusher.flush_if_due()

        assert flushes == [1]

    def it_flushes_pending_results_once_the_interval_has_elapsed(self) -> None:
        flushes: list[int] = []
        clock = FakeClock()
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=100, every_seconds=5.0, clock=clock)

        flusher.note_result()
        clock.now = 5.0
        flusher.flush_if_due()

        assert flushes == [1]

    def it_does_not_flush_on_the_interval_when_nothing_is_pending(self) -> None:
        flushes: list[int] = []
        clock = FakeClock()
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=100, every_seconds=5.0, clock=clock)

        clock.now = 50.0
        flusher.flush_if_due()

        assert flushes == []

    def it_measures_the_interval_from_the_last_flush(self) -> None:
        flushes: list[int] = []
        clock = FakeClock()
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=100, every_seconds=5.0, clock=clock)
        flusher.note_result()
        clock.now = 5.0
        flusher.flush_if_due()

        flusher.note_result()
        clock.now = 9.0
        flusher.flush_if_due()

        assert flushes == [1]

    def it_flushes_on_demand_only_when_something_is_pending(self) -> None:
        flushes: list[int] = []
        flusher = PeriodicFlusher(lambda: flushes.append(1), every_results=100, every_seconds=5.0, clock=FakeClock())

        flusher.flush()
        flusher.note_result()
        flusher.flush()

        assert flushes == [1]
