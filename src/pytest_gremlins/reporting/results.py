"""GremlinResult dataclass for tracking mutation test outcomes.

Each GremlinResult represents the outcome of testing a single mutation (gremlin).
Results track whether the gremlin was zapped (caught by tests) or survived
(test gap found).
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import TYPE_CHECKING

from pytest_gremlins.config import MAX_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pytest_gremlins.instrumentation.gremlin import Gremlin


TIMEOUT_NOT_CONFIRMED_PREFIX = "timeout not counted as a kill: the gremlin's tests are too slow even without the mutant"
"""Start of the ``error_output`` of a timeout that was downgraded to ERROR."""


CAPPED_LIMIT_ADVICE = f'the limit is capped at {MAX_TIMEOUT_SECONDS}s; lower --reruns or --reruns-delay'
"""What to do instead of raising a limit that rerun scaling already pushed to ``MAX_TIMEOUT_SECONDS``."""


MAXIMUM_LIMIT_ADVICE = f'the limit is already at the {MAX_TIMEOUT_SECONDS}s maximum'
"""Why a limit configured at ``MAX_TIMEOUT_SECONDS`` cannot be raised; lowering the reruns would leave it there."""


MUTANT_TIMEOUT_RAISE_ADVICE = 'raise {limit} with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout'
"""How to raise the per-gremlin timeout; ``{limit}`` is where the name of the limit goes."""


def limit_is_capped(timeout: int) -> bool:
    """Return whether ``timeout`` is the longest limit there is, so raising the per-attempt limit cannot help."""
    return timeout >= MAX_TIMEOUT_SECONDS


def scaled_limit_note(attempt_timeout: int | None, scaled_timeout: int) -> str:
    """Return the ``(Ns per attempt, ...)`` aside for a limit that rerun scaling widened, else an empty string."""
    if attempt_timeout is None or attempt_timeout == scaled_timeout:
        return ''
    return f' ({attempt_timeout}s per attempt, scaled for the pytest-rerunfailures budget)'


def limit_advice(limit: int | None, attempt_timeout: int | None, *, unscaled_name: str, raise_advice: str) -> str:
    """Return what to do about a timeout limit: raise it, or what is left when it cannot be raised.

    Args:
        limit: The limit the run used, or ``None`` when unknown.
        attempt_timeout: The configured limit before rerun scaling, or ``None`` when unknown.
        unscaled_name: What to call the limit when rerun scaling did not widen it.
        raise_advice: How to raise the limit, with ``{limit}`` where its name goes.

    Returns:
        A lowercase clause with no closing punctuation.
    """
    is_scaled = limit is not None and bool(scaled_limit_note(attempt_timeout, limit))
    if limit is not None and limit_is_capped(limit):
        return CAPPED_LIMIT_ADVICE if is_scaled else MAXIMUM_LIMIT_ADVICE
    return raise_advice.format(limit='the per-attempt limit' if is_scaled else unscaled_name)


def mutant_timeout_advice(limit: int | None, attempt_timeout: int | None, *, unscaled_name: str, tests: str) -> str:
    """Return the sentence closing a downgraded-timeout message: the limit's remedy, then speeding up ``tests``.

    Args:
        limit: The limit the run used, or ``None`` when unknown.
        attempt_timeout: The configured limit before rerun scaling, or ``None`` when unknown.
        unscaled_name: What to call the limit when rerun scaling did not widen it.
        tests: What to call the slow tests.

    Returns:
        A complete sentence.
    """
    advice = limit_advice(limit, attempt_timeout, unscaled_name=unscaled_name, raise_advice=MUTANT_TIMEOUT_RAISE_ADVICE)
    conjunction = 'so' if advice == MAXIMUM_LIMIT_ADVICE else 'or'
    return f'{advice[0].upper()}{advice[1:]}, {conjunction} speed up {tests}.'


class GremlinResultStatus(Enum):
    """Status of a gremlin after mutation testing.

    Attributes:
        ZAPPED: Test caught the mutation (good! tests are working)
        SURVIVED: Mutation not caught (test gap found)
        TIMEOUT: Test execution timed out
        ERROR: Error occurred during test execution
    """

    ZAPPED = 'zapped'
    SURVIVED = 'survived'
    TIMEOUT = 'timeout'
    ERROR = 'error'
    PARDONED = 'pardoned'


@dataclass(frozen=True)
class GremlinResult:
    """Result of testing a single gremlin (mutation).

    Attributes:
        gremlin: The gremlin that was tested.
        status: Outcome of the mutation test.
        killing_test: Name of the test that killed this gremlin (if zapped).
        execution_time_ms: Time taken to test this gremlin in milliseconds.
        error_output: Captured stderr or exception message when status is ERROR.
        selected_tests: Test node IDs selected to run against this gremlin.
    """

    gremlin: Gremlin
    status: GremlinResultStatus
    killing_test: str | None = None
    execution_time_ms: float | None = None
    error_output: str = ''
    selected_tests: list[str] = field(default_factory=list)

    @property
    def is_zapped(self) -> bool:
        """Return True if this gremlin was caught by tests."""
        return self.status == GremlinResultStatus.ZAPPED

    @property
    def is_survived(self) -> bool:
        """Return True if this gremlin escaped the tests."""
        return self.status == GremlinResultStatus.SURVIVED
