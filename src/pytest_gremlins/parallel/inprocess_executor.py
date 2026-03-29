"""In-process executor for mutation testing via __gremlin_active__ toggling.

Eliminates subprocess overhead by toggling module-level ``__gremlin_active__``
variables directly in the current process, then calling test functions.
This is 263x faster than subprocess per mutation on microbenchmarks.

Limitation: import-time mutations (expressions evaluated at module load)
are not detected because ``__gremlin_active__`` is toggled after import.
This accounts for ~15% of mutations. A future import-time classifier
will route those to the subprocess executor.
"""

from __future__ import annotations

from collections.abc import Callable
import enum
import logging
import sys
import time
from typing import Any

from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


class _TestOutcome(enum.Enum):
    """Tri-state outcome from running a single test spec.

    Distinguishes between a test that caught a mutation (FAILED),
    a test that passed (PASSED), and an infrastructure error that
    prevented the test from running at all (ERROR).
    """

    PASSED = 'passed'
    FAILED = 'failed'
    ERROR = 'error'


logger = logging.getLogger(__name__)


class InProcessExecutor:
    """Execute gremlin tests in-process by toggling __gremlin_active__.

    Attributes:
        timeout: Maximum seconds per gremlin test.
    """

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    @property
    def timeout(self) -> int:
        """Return the timeout in seconds."""
        return self._timeout

    def execute(
        self,
        gremlin_ids: list[str],
        gremlin_module_map: dict[str, str],
        test_specs: list[str],
    ) -> list[WorkerResult]:
        """Test gremlins by toggling __gremlin_active__ and running tests in-process.

        For each gremlin: sets the target module's ``__gremlin_active__`` to the
        gremlin ID, runs all test specs, records the result, then resets to None.

        Args:
            gremlin_ids: Gremlin IDs to test.
            gremlin_module_map: Mapping of gremlin ID to module name.
            test_specs: Test node IDs (e.g. ``'tests/test_foo.py::test_bar'``).

        Returns:
            List of WorkerResult, one per gremlin.
        """
        if not gremlin_ids:
            return []

        results: list[WorkerResult] = []
        for gremlin_id in gremlin_ids:
            result = self._test_single_gremlin(gremlin_id, gremlin_module_map, test_specs)
            results.append(result)

        return results

    def _test_single_gremlin(
        self,
        gremlin_id: str,
        gremlin_module_map: dict[str, str],
        test_specs: list[str],
    ) -> WorkerResult:
        """Toggle __gremlin_active__, run tests, reset, return result."""
        module_name = gremlin_module_map.get(gremlin_id)
        module = sys.modules.get(module_name) if module_name else None

        start = time.monotonic()
        try:
            if module is not None:
                module.__gremlin_active__ = gremlin_id  # type: ignore[attr-defined]

            for spec in test_specs:
                outcome = _run_test_spec(spec)
                if outcome is _TestOutcome.FAILED:
                    elapsed_ms = (time.monotonic() - start) * 1000
                    return WorkerResult(
                        gremlin_id=gremlin_id,
                        status=GremlinResultStatus.ZAPPED,
                        killing_test=spec,
                        execution_time_ms=elapsed_ms,
                    )
                if outcome is _TestOutcome.ERROR:
                    elapsed_ms = (time.monotonic() - start) * 1000
                    return WorkerResult(
                        gremlin_id=gremlin_id,
                        status=GremlinResultStatus.ERROR,
                        execution_time_ms=elapsed_ms,
                        error_output=f'Infrastructure error running {spec}',
                    )

            elapsed_ms = (time.monotonic() - start) * 1000
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.SURVIVED,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning('Error testing gremlin %s in-process: %s', gremlin_id, exc)
            return WorkerResult(
                gremlin_id=gremlin_id,
                status=GremlinResultStatus.ERROR,
                execution_time_ms=elapsed_ms,
                error_output=str(exc)[:2000],
            )
        finally:
            if module is not None:
                module.__gremlin_active__ = None  # type: ignore[attr-defined]


def _run_test_spec(spec: str) -> _TestOutcome:
    """Run a single test spec in-process.

    Returns:
        ``PASSED`` if the test callable ran without exception.
        ``FAILED`` if the test callable raised an exception (mutation caught).
        ``ERROR`` if the module or callable could not be resolved (infrastructure).

    Handles both function-level (``module::func``) and class-level
    (``module::Class::method``) test node IDs.
    """
    parts = spec.split('::')
    module = sys.modules.get(parts[0])
    if module is None:
        return _TestOutcome.ERROR

    callable_fn = _resolve_test_callable(module, parts[1:])
    if callable_fn is None:
        return _TestOutcome.ERROR

    try:
        callable_fn()
    except Exception:
        return _TestOutcome.FAILED
    return _TestOutcome.PASSED


def _resolve_test_callable(module: object, parts: list[str]) -> Callable[..., Any] | None:
    """Resolve a test callable from module and node ID parts."""
    if len(parts) == 2:  # noqa: PLR2004
        cls = getattr(module, parts[0], None)
        if cls is None:
            return None
        return getattr(cls(), parts[1], None)
    if len(parts) == 1:
        return getattr(module, parts[0], None)
    return None
