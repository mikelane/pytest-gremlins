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


MAXIMUM_LIMIT_ADVICE = f'the limit is already at the {MAX_TIMEOUT_SECONDS}s maximum; lower any reruns or rerun delays'
"""What to do about a limit configured at ``MAX_TIMEOUT_SECONDS``: it cannot rise, but reruns still spend it."""


MUTANT_TIMEOUT_RAISE_ADVICE = 'raise {limit} with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout'
"""How to raise the per-gremlin timeout; ``{limit}`` is where the name of the limit goes."""


COVERAGE_TIMEOUT_RAISE_ADVICE = 'set coverage_timeout / --gremlin-coverage-timeout to raise {limit}'
"""How to raise the coverage pre-scan timeout; ``{limit}`` is where the name of the limit goes."""


def limit_is_capped(timeout: int) -> bool:
    """Return whether ``timeout`` is the longest limit there is, so raising the per-attempt limit cannot help."""
    return timeout >= MAX_TIMEOUT_SECONDS


def limit_was_scaled(attempt_timeout: int | None, limit: int | None) -> bool:
    """Return whether rerun scaling widened ``attempt_timeout`` into ``limit``; ``False`` when either is unknown."""
    return attempt_timeout is not None and limit is not None and attempt_timeout != limit


def scaled_limit_note(attempt_timeout: int | None, scaled_timeout: int) -> str:
    """Return the ``(Ns per attempt, ...)`` aside for a limit that rerun scaling widened, else an empty string."""
    if not limit_was_scaled(attempt_timeout, scaled_timeout):
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

    Examples:
        >>> limit_advice(130, 30, unscaled_name='it', raise_advice='raise {limit}')
        'raise the per-attempt limit'
        >>> limit_advice(86400, 86400, unscaled_name='it', raise_advice='raise {limit}')
        'the limit is already at the 86400s maximum; lower any reruns or rerun delays'
    """
    is_scaled = limit_was_scaled(attempt_timeout, limit)
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

    Examples:
        >>> mutant_timeout_advice(86400, 30000, unscaled_name='the limit', tests='these tests')
        'The limit is capped at 86400s; lower --reruns or --reruns-delay, or speed up these tests.'
    """
    advice = limit_advice(limit, attempt_timeout, unscaled_name=unscaled_name, raise_advice=MUTANT_TIMEOUT_RAISE_ADVICE)
    return f'{advice[0].upper()}{advice[1:]}, or speed up {tests}.'


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
