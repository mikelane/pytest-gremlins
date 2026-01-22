"""GremlinResult dataclass for tracking mutation test outcomes.

Each GremlinResult represents the outcome of testing a single mutation (gremlin).
Results track whether the gremlin was zapped (caught by tests) or survived
(test gap found).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pytest_gremlins.instrumentation.gremlin import Gremlin


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


@dataclass(frozen=True)
class GremlinResult:
    """Result of testing a single gremlin (mutation).

    Attributes:
        gremlin: The gremlin that was tested.
        status: Outcome of the mutation test.
        killing_test: Name of the test that killed this gremlin (if zapped).
        execution_time_ms: Time taken to test this gremlin in milliseconds.
    """

    gremlin: Gremlin
    status: GremlinResultStatus
    killing_test: str | None = None
    execution_time_ms: float | None = None

    @property
    def is_zapped(self) -> bool:
        """Return True if this gremlin was caught by tests."""
        return self.status == GremlinResultStatus.ZAPPED

    @property
    def is_survived(self) -> bool:
        """Return True if this gremlin escaped the tests."""
        return self.status == GremlinResultStatus.SURVIVED
