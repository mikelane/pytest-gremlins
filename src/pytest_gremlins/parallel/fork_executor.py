"""Fork-per-batch executor for mutation testing with process isolation.

Forks once per batch of gremlins, runs InProcessExecutor in the child,
and pipes serialized results back to the parent via ``os.pipe()``.
This provides process isolation (protecting the parent from side effects)
without the overhead of full subprocess startup.

On platforms without ``os.fork`` (Windows), falls back to running
InProcessExecutor directly in the current process.
"""

from __future__ import annotations

import json
import logging
import os

from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus

logger = logging.getLogger(__name__)


class ForkExecutor:
    """Execute gremlin tests in forked child processes for isolation.

    Each batch of gremlins is executed in a forked child process using
    InProcessExecutor. Results are serialized as JSON and sent back
    through a pipe.

    Attributes:
        batch_size: Number of gremlins per fork.
        timeout: Maximum seconds per gremlin test.
    """

    def __init__(self, batch_size: int = 50, timeout: int = 30) -> None:
        self._batch_size = batch_size
        self._timeout = timeout

    @property
    def batch_size(self) -> int:
        """Return the batch size."""
        return self._batch_size

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
        """Test gremlins in forked child processes, one fork per batch.

        Args:
            gremlin_ids: Gremlin IDs to test.
            gremlin_module_map: Mapping of gremlin ID to module name.
            test_specs: Test node IDs to run against each gremlin.

        Returns:
            List of WorkerResult, one per gremlin.
        """
        if not gremlin_ids:
            return []

        if not hasattr(os, 'fork'):
            logger.info('os.fork unavailable, falling back to in-process execution')
            return InProcessExecutor(self._timeout).execute(gremlin_ids, gremlin_module_map, test_specs)

        # Everything below requires os.fork — unreachable on Windows,
        # tested on macOS/Linux via medium-marked fork tests.
        batches = [gremlin_ids[i : i + self._batch_size] for i in range(0, len(gremlin_ids), self._batch_size)]
        all_results: list[WorkerResult] = []

        for batch in batches:  # pragma: no cover — fork-only path, tested on Unix
            results = self._execute_batch_in_fork(batch, gremlin_module_map, test_specs)
            all_results.extend(results)

        return all_results  # pragma: no cover — fork-only path

    def _execute_batch_in_fork(  # pragma: no cover — fork-only, tested on Unix
        self,
        batch: list[str],
        gremlin_module_map: dict[str, str],
        test_specs: list[str],
    ) -> list[WorkerResult]:
        """Fork a child process, run a batch, pipe results back."""
        read_fd, write_fd = os.pipe()
        pid = os.fork()

        if pid == 0:  # pragma: no cover — child calls os._exit(); coverage cannot flush
            # Child process
            os.close(read_fd)
            try:
                results = InProcessExecutor(self._timeout).execute(batch, gremlin_module_map, test_specs)
                payload = json.dumps(
                    [
                        {
                            'gremlin_id': r.gremlin_id,
                            'status': r.status.value,
                            'execution_time_ms': r.execution_time_ms,
                            'killing_test': r.killing_test,
                            'error_output': r.error_output,
                        }
                        for r in results
                    ]
                )
                os.write(write_fd, payload.encode())
            finally:
                os.close(write_fd)
                os._exit(0)
        else:
            # Parent process
            os.close(write_fd)
            chunks: list[bytes] = []
            while True:
                data = os.read(read_fd, 65536)
                if not data:
                    break
                chunks.append(data)
            os.close(read_fd)
            os.waitpid(pid, 0)

            raw = json.loads(b''.join(chunks))
            return [
                WorkerResult(
                    gremlin_id=r['gremlin_id'],
                    status=GremlinResultStatus(r['status']),
                    execution_time_ms=r['execution_time_ms'],
                    killing_test=r.get('killing_test'),
                    error_output=r.get('error_output', ''),
                )
                for r in raw
            ]
