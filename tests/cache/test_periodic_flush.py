"""Tests for the periodic flush policy that keeps cached results durable during a long run (issue #974)."""

from __future__ import annotations

import logging
import sqlite3

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


class FailingThenWorkingFlush:
    def __init__(self, failures: int) -> None:
        self.failures_left = failures
        self.successes = 0

    def __call__(self) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise sqlite3.OperationalError('database or disk is full')
        self.successes += 1


@pytest.mark.small
class DescribePeriodicFlusherWhenFlushFails:
    def it_does_not_raise_and_keeps_the_pending_results(self) -> None:
        flush = FailingThenWorkingFlush(failures=1)
        flusher = PeriodicFlusher(flush, every_results=1, every_seconds=5.0, clock=FakeClock())
        flusher.note_result()

        flusher.flush_if_due()
        flusher.flush()

        assert flush.successes == 1

    def it_warns_once_however_many_flushes_fail(self, caplog: pytest.LogCaptureFixture) -> None:
        flusher = PeriodicFlusher(
            FailingThenWorkingFlush(failures=3), every_results=1, every_seconds=5.0, clock=FakeClock()
        )
        flusher.note_result()

        with caplog.at_level(logging.WARNING):
            flusher.flush()
            flusher.flush()
            flusher.flush()

        assert len([record for record in caplog.records if record.levelno == logging.WARNING]) == 1

    def it_names_the_error_in_the_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        flusher = PeriodicFlusher(FailingThenWorkingFlush(failures=1), every_results=1, clock=FakeClock())
        flusher.note_result()

        with caplog.at_level(logging.WARNING):
            flusher.flush()

        assert 'database or disk is full' in caplog.text

    def it_waits_a_full_interval_before_retrying_a_failed_count_flush(self) -> None:
        flush = FailingThenWorkingFlush(failures=1)
        clock = FakeClock()
        flusher = PeriodicFlusher(flush, every_results=1, every_seconds=5.0, clock=clock)
        flusher.note_result()
        flusher.flush_if_due()

        clock.now = 4.0
        flusher.flush_if_due()
        retried_too_early = flush.successes

        clock.now = 5.0
        flusher.flush_if_due()

        assert (retried_too_early, flush.successes) == (0, 1)
