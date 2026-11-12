"""Run the coverage pre-scan as several concurrent serial processes and combine their data (issue #527).

Each shard is the same ``coverage run -m pytest_gremlins.coverage.prescan_main`` command the single-process
pre-scan uses, given its own node ids and its own coverage data file. There is no pytest-xdist involved: every shard
is a plain serial pytest run, so coverage.py traces every test in it.

Session- and package-scoped fixtures run once per shard, so their code is credited to the first test of every shard:
the combined map holds every entry a single process records, plus those fixture lines. Gremlins in fixture code
therefore select more tests, never fewer.

Each shard also gets its own ``--basetemp``, placed last so it overrides a ``--basetemp`` from the project's addopts
or ``PYTEST_ADDOPTS`` (pytest prepends both). Without it, every shard would clear and reuse the same directory and
delete the live temp files of the others, as pytest-xdist workers avoid by the same means.

Where the shard basetemps live keeps a shard's ``tmp_path`` no longer than the serial pre-scan's, so a test that binds
an ``AF_UNIX`` socket there stays under the 104-byte limit on macOS in a shard exactly as it does serially:

- When the session has a ``--basetemp``, the serial pre-scan honours it, so shard ``i`` uses ``<basetemp>/<i>``.
- Otherwise the scratch directory is made under ``PYTEST_DEBUG_TEMPROOT`` when that is set and under the system
  temporary directory when not (pytest's own choice of root), and shard ``i`` uses ``<scratch>/<i>/b``. The scratch
  directory and its entries have deliberately short names (``pgsXXXXXXXX``).

Each shard's coverage data file and node id file stay in the scratch directory either way.

The outcome is all or nothing. If any shard times out, cannot be started, crashes or leaves no data, the caller gets
no data files at all, because a map built from some of the shards would claim that lines no test covers are
uncovered. The caller then runs without coverage-guided selection.
"""

from __future__ import annotations

from collections.abc import (
    Mapping,
    Sequence,
)
import gc
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import warnings

import coverage
from coverage.exceptions import (
    CoverageException,
    CoverageWarning,
)

from pytest_gremlins.coverage.prescan_shards import split_into_shards
from pytest_gremlins.node_id_file import command_with_node_ids_file

# pytest exits 0 when all tests pass and 1 when some fail; the pre-scan records coverage either way. Anything else
# (2 interrupted, such as a collection error; 3 internal error; 4 usage error) means the shard did not run its tests.
_FINISHED_EXIT_CODES = frozenset({0, 1})
_POLL_INTERVAL_SECONDS = 0.05
_OUTPUT_TAIL_BYTES = 1000
_SHARD_OUTPUT_NAME = 'output.log'

logger = logging.getLogger(__name__)
# Without a handler, logging.lastResort prints the warning to stderr, duplicating the print below.
logger.addHandler(logging.NullHandler())


def run_prescan_shards(
    command: Sequence[str],
    shards: Sequence[Sequence[str]],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
    scratch_dir: Path,
    basetemp_root: Path | None = None,
) -> list[Path] | None:
    """Run ``command`` once per shard, all at the same time, and return each shard's coverage data file.

    Args:
        command: The pre-scan command, whose launcher understands ``--gremlins-node-ids-file``.
        shards: The node ids each shard runs.
        cwd: Directory every shard runs in.
        timeout: Seconds all shards together may take.
        env: Environment for every shard; ``COVERAGE_FILE`` is set per shard on top of it.
        scratch_dir: Existing directory that holds each shard's node id file and data file. The caller removes it.
        basetemp_root: Existing directory whose entry ``<index>`` is shard ``index``'s ``--basetemp``. By default each
            shard's basetemp is ``<index>/b`` inside ``scratch_dir``.

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
    failures: list[str] = []
    try:
        for index, shard in enumerate(shards):
            shard_dir = scratch_dir / str(index)
            shard_dir.mkdir()
            data_files.append(shard_dir / 'coverage.data')
            basetemp = shard_dir / 'b' if basetemp_root is None else basetemp_root / str(index)
            processes.append(_start_shard(command, shard, shard_dir, data_files[-1], basetemp, cwd=cwd, env=env))
        finished_cleanly = _wait_for_all(processes, deadline, timeout)
        failures = _describe_failed_shards(processes, data_files, scratch_dir)
    finally:
        _stop_all(processes)
    if not finished_cleanly or not all(path.is_file() for path in data_files):
        for failure in failures:
            logger.warning('pre-scan %s', failure)
            # The log record is invisible in a default run, and "no data" would blame the wrong cause.
            print(f'pytest-gremlins: pre-scan {failure}', file=sys.stderr)
        return None
    return data_files


def run_sharded_prescan(
    command: Sequence[str],
    node_ids: Sequence[str],
    *,
    worker_count: int,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
    combined: Path,
    user_basetemp: Path | None = None,
) -> bool:
    """Shard ``node_ids`` over at most ``worker_count`` processes and write their combined coverage to ``combined``.

    Args:
        command: The pre-scan command, whose launcher understands ``--gremlins-node-ids-file``.
        node_ids: Every node id the pre-scan runs.
        worker_count: The most shard processes to run at once.
        cwd: Directory every shard runs in.
        timeout: Seconds all shards together may take.
        env: Environment for every shard.
        combined: Path of the combined coverage data file to create.
        user_basetemp: The session's absolute ``--basetemp``, if it has one. Shard ``i`` then runs in
            ``<user_basetemp>/<i>``, as the serial pre-scan would run in ``user_basetemp``.

    Returns:
        ``True`` when ``combined`` was written; ``False`` when a shard failed, in which case nothing is written.

    Raises:
        subprocess.TimeoutExpired: If the shards are still running after ``timeout`` seconds.
        OSError: If the operating system cannot start a shard.
    """
    shards = split_into_shards(node_ids, worker_count)
    if user_basetemp is not None:
        user_basetemp.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix='pgs', dir=_scratch_root(env, user_basetemp), ignore_cleanup_errors=True
        ) as scratch:
            data_files = run_prescan_shards(
                command,
                shards,
                cwd=cwd,
                timeout=timeout,
                env=env,
                scratch_dir=Path(scratch),
                basetemp_root=user_basetemp,
            )
            if data_files is None:
                return False
            return _combined_without_error(data_files, combined)
    finally:
        if user_basetemp is not None:
            _remove_shard_basetemps(user_basetemp, len(shards))


def _scratch_root(env: Mapping[str, str], user_basetemp: Path | None) -> str | None:
    """Where pytest would put its temp files: nowhere special under a ``--basetemp``, else ``PYTEST_DEBUG_TEMPROOT``."""
    return None if user_basetemp is not None else env.get('PYTEST_DEBUG_TEMPROOT') or None


def _remove_shard_basetemps(basetemp: Path, shard_count: int) -> None:
    for index in range(shard_count):
        shutil.rmtree(basetemp / str(index), ignore_errors=True)


def combine_shard_data(data_files: Sequence[Path], combined: Path) -> None:
    """Merge the shards' coverage data into ``combined``, keeping each line's per-test contexts.

    Args:
        data_files: Coverage data files written by the shards.
        combined: Path of the data file to create.
    """
    with warnings.catch_warnings():
        # A user's ``filterwarnings = error`` must not turn coverage.py's notice about a bad file into a crash;
        # ``strict`` makes that file raise a CoverageException, which the caller handles.
        warnings.simplefilter('ignore', CoverageWarning)
        # ``config_file=False``: the project's coverage config belongs to the shards, not to this combine. Reading it
        # here would import its plugins and could store paths differently from the single-process pre-scan.
        coverage.Coverage(data_file=str(combined), config_file=False).combine(
            [str(path) for path in data_files], strict=True, keep=True
        )


def _combined_without_error(data_files: Sequence[Path], combined: Path) -> bool:
    try:
        combine_shard_data(data_files, combined)
    except (CoverageException, OSError):
        combined.unlink(missing_ok=True)
        succeeded = False
    else:
        succeeded = True
    _release_unreadable_data_connections()
    return succeeded


def _release_unreadable_data_connections() -> None:
    """Close the connection coverage.py leaves open on a data file it could not read.

    The connection is only freed by garbage collection, and pytest reports the resulting ResourceWarning against
    whichever unrelated test runs next. Collecting here, with the warning ignored, keeps it from surfacing there.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', ResourceWarning)
        gc.collect()


def _describe_failed_shards(
    processes: Sequence[subprocess.Popen[bytes]], data_files: Sequence[Path], scratch_dir: Path
) -> list[str]:
    """Describe each shard that already exited abnormally or without data, with a bounded tail of its output."""
    failures: list[str] = []
    for index, (process, data_file) in enumerate(zip(processes, data_files, strict=True)):
        exit_code = process.poll()
        if exit_code is None:
            continue
        if exit_code not in _FINISHED_EXIT_CODES:
            reason = f'exited with code {exit_code}'
        elif not data_file.is_file():
            reason = 'left no coverage data'
        else:
            continue
        output_tail = _output_tail(scratch_dir / str(index) / _SHARD_OUTPUT_NAME)
        failures.append(f'shard {index} {reason}; output tail: {output_tail!r}')
    return failures


def _output_tail(output_file: Path) -> str:
    try:
        with output_file.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - _OUTPUT_TAIL_BYTES))
            return stream.read().decode('utf-8', errors='replace')
    except OSError:
        return ''


def _start_shard(
    command: Sequence[str],
    node_ids: Sequence[str],
    shard_dir: Path,
    data_file: Path,
    basetemp: Path,
    *,
    cwd: Path,
    env: Mapping[str, str],
) -> subprocess.Popen[bytes]:
    # pytest-cache and bytecode writes are the only state shards would otherwise share through the project rootdir;
    # Windows file locking turns a race on them into a shard crash.
    shard_env = {**env, 'COVERAGE_FILE': str(data_file), 'PYTHONDONTWRITEBYTECODE': '1'}
    cache_options = ['-o', f'cache_dir={shard_dir / "cache"}']
    # pytest writes collection errors and INTERNALERROR tracebacks to stdout, so both streams go to one log.
    with (shard_dir / _SHARD_OUTPUT_NAME).open('wb') as output_file:
        return subprocess.Popen(  # Intentional: runs a pytest pre-scan command
            [*command_with_node_ids_file(command, node_ids, shard_dir), *cache_options, f'--basetemp={basetemp}'],
            cwd=str(cwd),
            env=shard_env,
            stdout=output_file,
            stderr=subprocess.STDOUT,
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
