"""The per-mutant timeout grows with the rerun budget pytest-rerunfailures gives each test (issue #655)."""

from __future__ import annotations

import pytest

from pytest_gremlins.config import MAX_TIMEOUT_SECONDS
from pytest_gremlins.rerun_options import scaled_mutant_timeout


@pytest.mark.small
class DescribeScaledMutantTimeout:
    @pytest.mark.parametrize('reruns', [0, -1])
    def it_returns_the_base_timeout_when_there_are_no_reruns(self, reruns: int) -> None:
        assert scaled_mutant_timeout(30, reruns=reruns, reruns_delay=20) == 30

    @pytest.mark.parametrize(
        ('base', 'reruns', 'delay', 'expected'),
        [
            (30, 1, 0, 60),
            (30, 2, 0, 90),
            (30, 2, 20, 130),
            (10, 3, 1, 43),
        ],
    )
    def it_allows_every_attempt_its_full_budget_plus_the_delays(
        self, base: int, reruns: int, delay: float, expected: int
    ) -> None:
        assert scaled_mutant_timeout(base, reruns=reruns, reruns_delay=delay) == expected

    @pytest.mark.parametrize(('delay', 'expected'), [(0.1, 61), (0.5, 61), (1.5, 62)])
    def it_rounds_the_total_delay_up_to_whole_seconds(self, delay: float, expected: int) -> None:
        assert scaled_mutant_timeout(30, reruns=1, reruns_delay=delay) == expected

    def it_rounds_the_summed_delay_not_each_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=4, reruns_delay=0.5) == 152

    @pytest.mark.parametrize('delay', [-5, -0.5])
    def it_treats_a_negative_delay_as_no_delay(self, delay: float) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=delay) == 90

    def it_never_exceeds_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(MAX_TIMEOUT_SECONDS, reruns=5, reruns_delay=100) == MAX_TIMEOUT_SECONDS

    def it_clamps_an_infinite_delay_to_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('inf')) == MAX_TIMEOUT_SECONDS

    def it_treats_a_delay_that_is_not_a_number_as_no_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('nan')) == 90
