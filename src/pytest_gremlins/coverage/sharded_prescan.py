"""Run the coverage pre-scan as several concurrent serial processes and combine their data (issue #527).

Each shard is the same ``coverage run -m pytest_gremlins.coverage.prescan_main`` command the single-process
pre-scan uses, given its own node ids and its own coverage data file. There is no pytest-xdist involved: every shard
is a plain serial pytest run, so coverage.py traces every test in it.

The outcome is all or nothing. If any shard times out, cannot be started, crashes or leaves no data, the caller gets
no data files at all, because a map built from some of the shards would claim that lines no test covers are
uncovered. The caller then runs without coverage-guided selection.
"""

from __future__ import annotations

from collections.abc import (
    Mapping,
    Sequence,
)
from pathlib import Path
import subprocess
import time

import coverage

from pytest_gremlins.node_id_file import command_with_node_ids_file

# pytest exits 0 when all tests pass and 1 when some fail; the pre-scan records coverage either way. Anything else
# (2 interrupted, such as a collection error; 3 internal error; 4 usage error) means the shard did not run its tests.
_FINISHED_EXIT_CODES = frozenset({0, 1})
_POLL_INTERVAL_SECONDS = 0.05


def run_prescan_shards(
    command: Sequence[str],
    shards: Sequence[Sequence[str]],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
    scratch_dir: Path,
) -> list[Path] | None:
    """Run ``command`` once per shard, all at the same time, and return each shard's coverage data file.

    Args:
        command: The pre-scan command, whose launcher understands ``--gremlins-node-ids-file``.
        shards: The node ids each shard runs.
        cwd: Directory every shard runs in.
        timeout: Seconds all shards together may take.
        env: Environment for every shard; ``COVERAGE_FILE`` is set per shard on top of it.
        scratch_dir: Existing directory that holds each shard's node id file and data file. The caller removes it.

    Returns:
        The data files, in shard order, or ``None`` when any shard crashed or recorded no data. Every shard is
        stopped before this returns.

    Raises:
        subprocess.TimeoutExpired: If the shards are still running after ``timeout`` seconds.
        OSError: If the operating system cannot start a shard.
    """
    deadline = time.monotonic() + timeout
    processes: list[subprocess.Popen[bytes]] = []
    data_files: list[Path] = []
    try:
        for index, shard in enumerate(shards):
            shard_dir = scratch_dir / f'shard_{index}'
            shard_dir.mkdir()
            data_files.append(shard_dir / 'coverage.data')
            processes.append(_start_shard(command, shard, shard_dir, data_files[-1], cwd=cwd, env=env))
        finished_cleanly = _wait_for_all(processes, deadline, timeout)
    finally:
        _stop_all(processes)
    if not finished_cleanly or not all(path.is_file() for path in data_files):
        return None
    return data_files


def combine_shard_data(data_files: Sequence[Path], combined: Path) -> None:
    """Merge the shards' coverage data into ``combined``, keeping each line's per-test contexts.

    Args:
        data_files: Coverage data files written by the shards.
        combined: Path of the data file to create.
    """
    coverage.Coverage(data_file=str(combined)).combine([str(path) for path in data_files], strict=True, keep=True)


def _start_shard(
    command: Sequence[str],
    node_ids: Sequence[str],
    shard_dir: Path,
    data_file: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # Intentional: runs a pytest pre-scan command
        command_with_node_ids_file(command, node_ids, shard_dir),
        cwd=str(cwd),
        env={**env, 'COVERAGE_FILE': str(data_file)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_all(processes: Sequence[subprocess.Popen[bytes]], deadline: float, timeout: float) -> bool:
    """Wait until every process finished its tests; ``False`` as soon as one did not."""
    running = list(processes)
    while running:
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired([str(process.args) for process in running], timeout)
        for process in list(running):
            exit_code = process.poll()
            if exit_code is None:
                continue
            if exit_code not in _FINISHED_EXIT_CODES:
                return False
            running.remove(process)
        if running:
            time.sleep(_POLL_INTERVAL_SECONDS)
    return True


def _stop_all(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait()
