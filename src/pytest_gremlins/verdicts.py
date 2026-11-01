"""Verdict decisions: how a gremlin's subprocess outcome becomes a verdict, and when a kill is confirmed.

Everything that assigns or changes a gremlin's verdict lives here, so the cache-version guard
(``tests/cache/test_cache_version_guard.py``) can hash this module instead of the much larger ``plugin.py``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace as dataclass_replace
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from pytest_gremlins.cache.incremental import MILLISECONDS_PER_SECOND
from pytest_gremlins.control_run import (
    MAX_SELECTION_FAILURE_OUTPUT_CHARS,
    SELECTION_FAILS_TO_LOAD_PREFIX,
    TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX,
    ControlRunOutcome,
    UnmutatedRunOutcome,
    run_control,
    run_unmutated,
)
from pytest_gremlins.instrumentation.spawn_hook import SOURCES_FILE_ENV_VAR as GREMLIN_SOURCES_ENV_VAR
from pytest_gremlins.instrumentation.spawn_hook import export_spawn_hook
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR
from pytest_gremlins.parallel.exit_codes import (
    COLLECTION_KILLING_TEST,
    GREMLIN_COLLECTION_FAILED_EXIT_CODE,
)
from pytest_gremlins.parallel.lightweight import (
    build_lightweight_command,
    describe_runner_error,
)
from pytest_gremlins.reporting.results import (
    CAPPED_LIMIT_ADVICE,
    TIMEOUT_NOT_CONFIRMED_PREFIX,
    GremlinResult,
    GremlinResultStatus,
    limit_is_capped,
    scaled_limit_note,
)
from pytest_gremlins.xdist_options import (
    addopts_without_xdist,
    env_without_xdist_addopts,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.plugin import GremlinSession

logger = logging.getLogger(__name__)

MAX_SELECTION_IDS_IN_MESSAGE = 5
"""Node ids named in a downgraded-timeout message before the rest are summarised as ``(and N more)``."""
TIMEOUT_CONFIRMATION_HEADROOM = 0.5
"""Share of ``mutant_timeout`` the unmutated confirmation run may use for a timeout to stay a kill.

One yes/no sample against the limit has no margin: an unmutated run that finishes at 99% of the limit
would keep a survivor as a kill on a lucky run. Requiring the unmutated run to fit in half the limit
means a real hang clears a 2x margin, while ordinary run-to-run noise does not.
"""


def _unmutated_command_and_env(gremlin_session: GremlinSession, rootdir: Path) -> tuple[list[str], dict[str, str]]:
    """Return a gremlin run's base command and environment, minus the gremlin."""
    instrumented_dir = gremlin_session.instrumented_dir
    command = _build_test_command(
        instrumented_dir,
        gremlin_session.preserved_addopts,
        xdist_loaded=gremlin_session.xdist_loaded,
        xdist_loader_options=gremlin_session.xdist_loader_options,
        doctest_ini_overrides=gremlin_session.doctest_ini_overrides,
        rerun_options=gremlin_session.rerun_options,
        pytest_cov_options=gremlin_session.pytest_cov_options,
    )
    env = env_without_xdist_addopts(os.environ)
    env.pop(ACTIVE_GREMLIN_ENV_VAR, None)
    env['GREMLIN_ROOTDIR'] = str(rootdir)
    if instrumented_dir is not None:
        env[GREMLIN_SOURCES_ENV_VAR] = str(instrumented_dir / 'sources.json')
    export_spawn_hook(env)
    return command, env


def _collect_unmutated(
    gremlin_session: GremlinSession,
    rootdir: Path,
    node_ids: Sequence[str],
) -> ControlRunOutcome:
    """Collect ``node_ids`` with the bootstrap, using a gremlin run's command and env minus the gremlin."""
    command, env = _unmutated_command_and_env(gremlin_session, rootdir)
    return run_control(command, node_ids, rootdir, env, node_ids_dir=gremlin_session.instrumented_dir)


def _confirm_collection_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Keep a collection kill only if the unmutated run of the gremlin's own selection loads.

    The control run vouches for the union of all selected tests, but a gremlin collects only its
    own subset, and a subset can fail to load without its siblings (for example a module that
    needs ``sys.path`` changes made by another module). The check runs in the parent, where the
    result arrives, so the memo is shared by every execution mode and pool worker processes need
    no state of their own. It costs one collect-only run per distinct selection, and only for
    gremlins that were reported as collection kills.

    Args:
        result: The gremlin's result from the subprocess.
        node_ids: The node ids the gremlin's subprocess was asked to run, in command order.
        gremlin_session: The current gremlin session, holding the memo.
        rootdir: Root directory of the project.

    Returns:
        ``result`` unchanged, or an ERROR result when the unmutated selection fails to load.
    """
    if result.status != GremlinResultStatus.ZAPPED or result.killing_test != COLLECTION_KILLING_TEST:
        return result
    selection = tuple(node_ids)
    if selection not in gremlin_session.unmutated_load_checks:
        gremlin_session.unmutated_load_checks[selection] = _collect_unmutated(gremlin_session, rootdir, node_ids)
    outcome = gremlin_session.unmutated_load_checks[selection]
    if outcome.loads_cleanly:
        return result
    return dataclass_replace(
        result,
        status=GremlinResultStatus.ERROR,
        killing_test=None,
        error_output=f'{SELECTION_FAILS_TO_LOAD_PREFIX}\n{outcome.output[-MAX_SELECTION_FAILURE_OUTPUT_CHARS:]}',
    )


def _prefill_collection_kill_confirmations(
    pending: Sequence[tuple[GremlinResult, Sequence[str]]],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> None:
    """Fill the unmutated-load memo for every collection kill in ``pending``, running distinct selections concurrently.

    Collection confirmations measure no time, so they can overlap; timeout confirmations compare
    durations and must stay solo, so they are not touched here. Worker threads only run the
    subprocess; the memo is written from the calling thread, so it needs no lock. Concurrency is
    bounded by the configured worker count. :func:`_confirm_collection_kill` then reads the warm memo
    and decides each verdict exactly as before.

    Args:
        pending: Each result paired with the node ids its subprocess was asked to run.
        gremlin_session: The current gremlin session, holding the memo and the worker count.
        rootdir: Root directory of the project.
    """
    selections = {
        tuple(node_ids): node_ids
        for result, node_ids in pending
        if result.status == GremlinResultStatus.ZAPPED and result.killing_test == COLLECTION_KILLING_TEST
    }
    unchecked = [selection for selection in selections if selection not in gremlin_session.unmutated_load_checks]
    if not unchecked:
        return
    worker_count = min(len(unchecked), gremlin_session.parallel_workers or os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        outcomes = executor.map(
            lambda selection: _collect_unmutated(gremlin_session, rootdir, selections[selection]), unchecked
        )
        gremlin_session.unmutated_load_checks.update(zip(unchecked, outcomes, strict=True))


def _confirm_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Confirm a collection kill or a timeout against the gremlin's own unmutated selection."""
    result = _confirm_collection_kill(result, node_ids, gremlin_session, rootdir)
    return _confirm_timeout_kill(result, node_ids, gremlin_session, rootdir)


def _confirm_timeout_kill(
    result: GremlinResult,
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Keep a timeout as a kill only if the gremlin's own selection finishes in time without a mutant.

    A gremlin times out when its tests outlast ``mutant_timeout``. If the same tests outlast it
    with no mutant at all, the timeout says nothing about the mutant, and counting it as a kill
    would score a suite that asserts nothing as perfect. Such a result becomes an ERROR, which stays
    in the score's denominator, so a timeout that is too short can only lower the score. Like
    :func:`_confirm_collection_kill`, the check runs in the parent where the result arrives, so it
    covers every execution mode, and it runs once per distinct selection.

    Args:
        result: The gremlin's result from the subprocess.
        node_ids: The node ids the gremlin's subprocess was asked to run, in command order.
        gremlin_session: The current gremlin session, holding the memo and the timeout.
        rootdir: Root directory of the project.

    Returns:
        ``result`` unchanged, or an ERROR result when the unmutated selection times out, takes more than
        ``TIMEOUT_CONFIRMATION_HEADROOM`` of the limit, or cannot be launched.
    """
    if result.status != GremlinResultStatus.TIMEOUT:
        return result
    selection = tuple(node_ids)
    if selection not in gremlin_session.unmutated_timeout_checks:
        command, env = _unmutated_command_and_env(gremlin_session, rootdir)
        gremlin_session.unmutated_timeout_checks[selection] = run_unmutated(
            command,
            node_ids,
            rootdir,
            env,
            timeout=gremlin_session.mutant_timeout,
            node_ids_dir=gremlin_session.instrumented_dir,
        )
        outcome = gremlin_session.unmutated_timeout_checks[selection]
        logger.debug(
            'Timeout confirmation: unmutated run of %d node ids took %.1fs (timed out: %s)',
            len(selection),
            outcome.seconds,
            outcome.timed_out,
        )
    unmutated_outcome = gremlin_session.unmutated_timeout_checks[selection]
    if unmutated_outcome.launch_error is not None:
        return dataclass_replace(
            result,
            status=GremlinResultStatus.ERROR,
            error_output=f'{TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX} {unmutated_outcome.launch_error}',
        )
    mutant_timeout = gremlin_session.mutant_timeout
    fits_in_headroom = unmutated_outcome.seconds <= mutant_timeout * TIMEOUT_CONFIRMATION_HEADROOM
    if not unmutated_outcome.timed_out and fits_in_headroom:
        return result
    return dataclass_replace(
        result,
        status=GremlinResultStatus.ERROR,
        error_output=_timeout_not_confirmed_message(
            selection, mutant_timeout, unmutated_outcome, gremlin_session.mutant_attempt_timeout
        ),
    )


def _timeout_not_confirmed_message(
    selection: Sequence[str],
    mutant_timeout: int,
    unmutated_outcome: UnmutatedRunOutcome,
    attempt_timeout: int | None = None,
) -> str:
    """Explain a downgraded timeout: the selection, how the unmutated run went, the limit, and how to raise it."""
    shown_ids = ', '.join(selection[:MAX_SELECTION_IDS_IN_MESSAGE]) or 'the whole suite'
    hidden_count = len(selection) - MAX_SELECTION_IDS_IN_MESSAGE
    if hidden_count > 0:
        shown_ids += f' (and {hidden_count} more)'
    headroom_percent = f'{TIMEOUT_CONFIRMATION_HEADROOM:.0%}'
    scaled_note = scaled_limit_note(attempt_timeout, mutant_timeout)
    unmutated_run_summary = (
        f'did not finish in {mutant_timeout}s{scaled_note}'
        if unmutated_outcome.timed_out
        else (
            f'took {unmutated_outcome.seconds:.1f}s, over {headroom_percent} of the {mutant_timeout}s limit'
            f'{scaled_note}'
        )
    )
    raised_limit = 'the per-attempt limit' if scaled_note else 'the limit'
    is_capped = bool(scaled_note) and limit_is_capped(mutant_timeout)
    advice = (
        f'{CAPPED_LIMIT_ADVICE[0].upper()}{CAPPED_LIMIT_ADVICE[1:]}'
        if is_capped
        else f'Raise {raised_limit} with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout'
    )
    return (
        f'{TIMEOUT_NOT_CONFIRMED_PREFIX} (selection: {shown_ids}; unmutated run {unmutated_run_summary}). '
        f'{advice}, or speed up these tests.'
    )


def _rerun_timeout_alone(
    result: GremlinResult,
    test_command: list[str],
    rootdir: Path,
    gremlin_session: GremlinSession,
) -> GremlinResult:
    """Re-run a pooled TIMEOUT by itself, so it competes with nothing the unmutated run does not.

    A gremlin that timed out among parallel workers or in a batch may only have been slowed by them
    (a shared lock, a saturated CPU), while the unmutated confirmation runs alone. Running the mutated
    gremlin alone under the same selection and timeout compares like with like; if it finishes, its
    verdict is scored as usual.

    Args:
        result: The pooled result.
        test_command: The command the pooled run used.
        rootdir: Root directory of the project.
        gremlin_session: The current gremlin session.

    Returns:
        ``result`` unchanged unless it is a TIMEOUT, otherwise the solo run's result.
    """
    if result.status != GremlinResultStatus.TIMEOUT:
        return result
    solo_result = _test_gremlin(
        result.gremlin,
        test_command,
        rootdir,
        gremlin_session.instrumented_dir,
        timeout=gremlin_session.mutant_timeout,
    )
    logger.debug('Pooled timeout of %s re-run alone: %s', result.gremlin.gremlin_id, solo_result.status.value)
    return dataclass_replace(solo_result, selected_tests=result.selected_tests)


def _confirm_pooled_result(
    result: GremlinResult,
    test_command: list[str],
    node_ids: Sequence[str],
    gremlin_session: GremlinSession,
    rootdir: Path,
) -> GremlinResult:
    """Judge a parallel or batch result: re-run a timeout alone, then apply the usual confirmations."""
    result = _rerun_timeout_alone(result, test_command, rootdir, gremlin_session)
    return _confirm_kill(result, node_ids, gremlin_session, rootdir)


def _build_test_command(
    instrumented_dir: Path | None,
    preserved_addopts: str = '',
    *,
    xdist_loaded: bool = False,
    xdist_loader_options: Sequence[str] = (),
    doctest_ini_overrides: Sequence[str] = (),
    rerun_options: Sequence[str] = (),
    pytest_cov_options: Sequence[str] = (),
) -> list[str]:
    """Build the command to run tests.

    If an instrumented directory is provided, uses the bootstrap script
    to register import hooks before running pytest. Otherwise, runs
    pytest directly.

    ``--no-cov`` arrives through ``pytest_cov_options`` and only when gremlin runs have pytest-cov
    loaded, so that runs without the plugin do not receive an unknown CLI flag (which causes pytest
    exit-code 4).

    Args:
        instrumented_dir: Directory containing bootstrap infrastructure, or None.
        preserved_addopts: The project's ``addopts`` with pytest-cov flags stripped
            (see :func:`_addopts_without_cov`), passed through as ``-o addopts=<...>``
            so collection-affecting options such as ``--import-mode=importlib`` survive
            into the subprocess. Defaults to ``''`` (clear all addopts). xdist options
            are dropped (see :func:`~pytest_gremlins.xdist_options.addopts_without_xdist`)
            so the tests run in the bootstrap process, where the gremlin import hook lives.
        xdist_loaded: Whether pytest-xdist is loaded in the main session.  If so, ``-n 0`` is
            appended as a second layer: argparse keeps the last value, so no spelling of ``-n``
            in ``addopts`` or ``PYTEST_ADDOPTS`` (for example a clustered ``-xn 2``, which the
            token stripper does not recognise) can distribute the run.  xdist itself stays
            loaded, so ``worker_id`` still works.  Without xdist the flag would be rejected as
            unrecognized, so it is omitted.
        xdist_loader_options: The ``-p`` loader for gremlin runs that start with autoload disabled (see
            :func:`_xdist_options_for`), placed before ``-n 0`` so the option has a plugin to parse it.
        doctest_ini_overrides: The session's resolved doctest ini values as ``-o key=value`` argument pairs
            (see :func:`_doctest_ini_overrides`), kept outside ``addopts`` because pytest before 9.1 ignores a
            ``-o`` nested in an ``addopts`` value (issue #719).
        rerun_options: pytest-rerunfailures options typed on the command line (see
            :func:`~pytest_gremlins.rerun_options.rerun_options_in`), appended last so they win over
            ``addopts`` as they do in the baseline run.  A flaky test then has to fail on every
            attempt before it can zap a gremlin (issue #546).
        pytest_cov_options: The ``--no-cov`` flag, preceded by a ``-p`` loader when gremlin runs start with
            autoload disabled (see :func:`_pytest_cov_options_for`); empty when they do not load pytest-cov.

    Returns:
        Command list to run tests.
    """
    gremlin_addopts = addopts_without_xdist(preserved_addopts)
    if instrumented_dir is not None:
        bootstrap_script = instrumented_dir / 'gremlin_bootstrap.py'
        command = [
            sys.executable,
            str(bootstrap_script),
            '-x',
            '--tb=no',
            '-q',
            '-o',
            f'addopts={gremlin_addopts}',
            *doctest_ini_overrides,
        ]
    else:
        command = [
            sys.executable,
            '-m',
            'pytest',
            '-x',
            '--tb=no',
            '-q',
            '-o',
            f'addopts={gremlin_addopts}',
            *doctest_ini_overrides,
        ]

    command.extend(pytest_cov_options)

    if xdist_loaded:
        command.extend([*xdist_loader_options, '-n', '0'])

    command.extend(rerun_options)

    return command


def _test_gremlin(
    gremlin: Gremlin,
    test_command: list[str],
    rootdir: Path,
    instrumented_dir: Path | None,
    *,
    timeout: int,
) -> GremlinResult:
    """Test a single gremlin and record how long the run took.

    The elapsed time lets the incremental cache reuse the verdict under a different mutant timeout (#567).

    Args:
        gremlin: The gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory of the project.
        instrumented_dir: Directory containing bootstrap infrastructure.
        timeout: Seconds the test run may take before the gremlin is reported as a timeout.

    Returns:
        Result of testing the gremlin, with ``execution_time_ms`` set.
    """
    started = time.monotonic()
    result = _run_gremlin_subprocess(gremlin, test_command, rootdir, instrumented_dir, timeout=timeout)
    elapsed_ms = (time.monotonic() - started) * MILLISECONDS_PER_SECOND
    return dataclass_replace(result, execution_time_ms=elapsed_ms)


def _run_gremlin_subprocess(
    gremlin: Gremlin,
    test_command: list[str],
    rootdir: Path,
    instrumented_dir: Path | None,
    *,
    timeout: int,
) -> GremlinResult:
    """Test a single gremlin by running tests with the mutation active.

    The subprocess runs via a bootstrap script that registers import hooks
    to intercept module imports and provide instrumented code. The active
    gremlin ID is passed via the ACTIVE_GREMLIN environment variable.

    Args:
        gremlin: The gremlin to test.
        test_command: Command to run tests.
        rootdir: Root directory of the project.
        instrumented_dir: Directory containing bootstrap infrastructure.
        timeout: Seconds the test run may take before the gremlin is reported as a timeout.

    Returns:
        Result of testing the gremlin.
    """
    env = env_without_xdist_addopts(os.environ)
    env[ACTIVE_GREMLIN_ENV_VAR] = gremlin.gremlin_id
    env['GREMLIN_ROOTDIR'] = str(rootdir)

    if instrumented_dir is not None:
        sources_file = instrumented_dir / 'sources.json'
        env[GREMLIN_SOURCES_ENV_VAR] = str(sources_file)
    export_spawn_hook(env)

    # Single routing point for the lightweight runner. It always returns None while the runner is
    # disabled (#538), so every gremlin runs through the pytest bootstrap.
    lightweight_cmd = build_lightweight_command(test_command, env)
    effective_command = lightweight_cmd if lightweight_cmd is not None else test_command

    try:
        subprocess_outcome = subprocess.run(  # Intentional: runs pytest test commands
            effective_command,
            cwd=str(rootdir),
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        # pytest uses specific exit codes. Only exit code 1 means tests ran
        # and failed (i.e. the mutation was caught). Other non-zero exit codes
        # indicate errors (collection/import/internal) and should not be counted
        # as zapped.
        if subprocess_outcome.returncode == 0:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.SURVIVED,
            )
        if subprocess_outcome.returncode == 1:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ZAPPED,
                killing_test='unknown',
            )
        if subprocess_outcome.returncode == GREMLIN_COLLECTION_FAILED_EXIT_CODE:
            return GremlinResult(
                gremlin=gremlin,
                status=GremlinResultStatus.ZAPPED,
                killing_test=COLLECTION_KILLING_TEST,
            )
        error_output = describe_runner_error(subprocess_outcome.returncode, subprocess_outcome.stderr)
        logger.debug(
            'Gremlin %s error (exit %d): %s',
            gremlin.gremlin_id,
            subprocess_outcome.returncode,
            error_output[:200],
        )
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
            error_output=error_output,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.TIMEOUT,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning('Error testing gremlin %s: %s', gremlin.gremlin_id, exc)
        return GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
            error_output=str(exc)[:2000],
        )
