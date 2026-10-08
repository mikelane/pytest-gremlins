"""A gremlin's test command keeps its node ids in a file, so a full-suite selection fits Windows' limit (#485).

Every test mocks ``subprocess.run`` and runs on every OS: the invariant is about what the command holds.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from pytest_gremlins.control_run import (
    run_control,
    run_unmutated,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.node_id_file import NODE_IDS_FILE_OPTION
from pytest_gremlins.plugin import (
    GremlinSession,
    _build_filtered_test_command,
    _collect_unmutated,
    _confirm_timeout_kill,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

WINDOWS_MAX_CMDLINE = 32_767
BASE_COMMAND = ['python', 'gremlin_bootstrap.py', '-x', '--tb=no', '-q', '-o', 'addopts=']

# The shape of the ids in the issue's report: 430 of them, 53,818 characters once joined.
REPORTED_NODE_IDS = [
    f'tests/unit/entities/test_entity_registry_{i // 20}.py'
    f'::test_entity_for_route_maps_registry_key_{i}[ExampleFacility-ExampleFacility]'
    for i in range(430)
]
TEST_NAMES = [f'test_entity_for_route_maps_registry_key_{i}' for i in range(430)]


def _node_ids_in_file(command: list[str]) -> list[str]:
    option = next(argument for argument in command if argument.startswith(f'{NODE_IDS_FILE_OPTION}='))
    return json.loads(Path(option.split('=', 1)[1]).read_text(encoding='utf-8'))


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    gremlin_session = GremlinSession(enabled=True, instrumented_dir=tmp_path, mutant_timeout=7)
    gremlin_session.test_node_ids = dict(zip(TEST_NAMES, REPORTED_NODE_IDS, strict=True))
    return gremlin_session


@pytest.mark.medium
class DescribeBuildFilteredTestCommand:
    def it_keeps_every_node_id_of_a_full_suite_selection_off_the_command_line(self, session: GremlinSession) -> None:
        command = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES, session)

        assert not set(REPORTED_NODE_IDS) & set(command)
        assert len(' '.join(command)) < WINDOWS_MAX_CMDLINE

    def it_stores_the_selected_node_ids_in_the_order_of_the_selection(self, session: GremlinSession) -> None:
        selection = [TEST_NAMES[5], TEST_NAMES[2], TEST_NAMES[9]]

        command = _build_filtered_test_command(BASE_COMMAND, selection, session)

        assert _node_ids_in_file(command) == [REPORTED_NODE_IDS[5], REPORTED_NODE_IDS[2], REPORTED_NODE_IDS[9]]

    def it_skips_names_that_have_no_node_id(self, session: GremlinSession) -> None:
        command = _build_filtered_test_command(BASE_COMMAND, ['unknown', TEST_NAMES[1]], session)

        assert _node_ids_in_file(command) == [REPORTED_NODE_IDS[1]]

    def it_keeps_the_base_command_in_front(self, session: GremlinSession) -> None:
        command = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES, session)

        assert command[: len(BASE_COMMAND)] == BASE_COMMAND

    def it_shares_one_file_between_equal_selections(self, session: GremlinSession) -> None:
        first = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES[:3], session)
        second = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES[:3], session)
        other = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES[:4], session)

        assert first == second
        assert first != other

    def it_adds_nothing_when_nothing_is_selected(self, session: GremlinSession) -> None:
        assert _build_filtered_test_command(BASE_COMMAND, [], session) == BASE_COMMAND

    def it_falls_back_to_the_command_line_without_an_instrumented_dir(self, session: GremlinSession) -> None:
        session.instrumented_dir = None

        command = _build_filtered_test_command(BASE_COMMAND, TEST_NAMES[:2], session)

        assert command == [*BASE_COMMAND, *REPORTED_NODE_IDS[:2]]


@pytest.mark.medium
class DescribeRunUnmutated:
    @staticmethod
    def _run(tmp_path: Path, node_ids: list[str], **kwargs: Path | None) -> list[str]:
        captured: list[str] = []

        def capture(command: list[str], **_kwargs: object) -> None:
            captured.extend(command)

        with patch('pytest_gremlins.control_run.subprocess.run', autospec=True, side_effect=capture):
            run_unmutated(BASE_COMMAND, node_ids, tmp_path, {}, timeout=5, **kwargs)
        return captured

    def it_keeps_every_node_id_off_the_command_line_when_given_a_directory(self, tmp_path: Path) -> None:
        command = self._run(tmp_path, REPORTED_NODE_IDS, node_ids_dir=tmp_path)

        assert not set(REPORTED_NODE_IDS) & set(command)
        assert len(' '.join(command)) < WINDOWS_MAX_CMDLINE
        assert _node_ids_in_file(command) == REPORTED_NODE_IDS

    def it_still_puts_the_ids_on_the_command_line_without_a_directory(self, tmp_path: Path) -> None:
        assert self._run(tmp_path, ['a.py::t']) == [*BASE_COMMAND, 'a.py::t']


@pytest.mark.medium
class DescribeRunControlCommand:
    @staticmethod
    def _run(tmp_path: Path, node_ids: list[str], **kwargs: Path | None) -> list[list[str]]:
        captured: list[list[str]] = []

        def finish(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            captured.append(command)
            return subprocess.CompletedProcess(command, 0, b'', b'')

        with patch('pytest_gremlins.control_run.subprocess.run', autospec=True, side_effect=finish):
            run_control(BASE_COMMAND, node_ids, tmp_path, {}, timeout=5, **kwargs)
        return captured

    def it_keeps_every_node_id_off_the_command_line_in_a_single_run(self, tmp_path: Path) -> None:
        (command,) = self._run(tmp_path, REPORTED_NODE_IDS, node_ids_dir=tmp_path)

        assert not set(REPORTED_NODE_IDS) & set(command)
        assert len(' '.join(command)) < WINDOWS_MAX_CMDLINE
        assert _node_ids_in_file(command) == REPORTED_NODE_IDS

    def it_collects_only_with_a_short_traceback(self, tmp_path: Path) -> None:
        (command,) = self._run(tmp_path, REPORTED_NODE_IDS, node_ids_dir=tmp_path)

        assert command[: len(BASE_COMMAND) + 2] == [*BASE_COMMAND, '--collect-only', '--tb=short']

    def it_collects_the_whole_suite_when_given_no_node_ids(self, tmp_path: Path) -> None:
        assert self._run(tmp_path, [], node_ids_dir=tmp_path) == [[*BASE_COMMAND, '--collect-only', '--tb=short']]

    def it_still_puts_the_ids_on_the_command_line_without_a_directory(self, tmp_path: Path) -> None:
        assert self._run(tmp_path, ['a.py::t']) == [[*BASE_COMMAND, '--collect-only', '--tb=short', 'a.py::t']]

    def it_reports_a_launch_failure_as_a_run_that_does_not_load(self, tmp_path: Path) -> None:
        too_long = OSError(206, 'The filename or extension is too long')

        with patch('pytest_gremlins.control_run.subprocess.run', autospec=True, side_effect=too_long):
            outcome = run_control(BASE_COMMAND, [], tmp_path, {}, timeout=5)

        assert outcome.loads_cleanly is False
        assert 'too long' in outcome.output


@pytest.mark.medium
class DescribeCollectUnmutatedCommand:
    def it_hands_the_instrumented_dir_to_the_control_run(self, session: GremlinSession, tmp_path: Path) -> None:
        captured: list[str] = []

        def finish(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            captured.extend(command)
            return subprocess.CompletedProcess(command, 0, b'', b'')

        with patch('pytest_gremlins.control_run.subprocess.run', autospec=True, side_effect=finish):
            _collect_unmutated(session, tmp_path, REPORTED_NODE_IDS)

        assert not set(REPORTED_NODE_IDS) & set(captured)
        assert _node_ids_in_file(captured) == REPORTED_NODE_IDS


@pytest.mark.medium
class DescribeTimeoutConfirmationCommand:
    def it_runs_the_unmutated_selection_from_a_node_ids_file(self, session: GremlinSession, tmp_path: Path) -> None:
        captured: list[str] = []
        gremlin = Gremlin(
            gremlin_id='g001',
            file_path='/path/to/source.py',
            line_number=1,
            original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
            mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
            operator_name='ComparisonOperatorSwap',
            description='> to >=',
        )

        def finish(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            captured.extend(command)
            return subprocess.CompletedProcess(command, 0)

        with patch('pytest_gremlins.control_run.subprocess.run', autospec=True, side_effect=finish):
            _confirm_timeout_kill(
                GremlinResult(gremlin=gremlin, status=GremlinResultStatus.TIMEOUT),
                REPORTED_NODE_IDS,
                session,
                tmp_path,
            )

        assert not set(REPORTED_NODE_IDS) & set(captured)
        assert _node_ids_in_file(captured) == REPORTED_NODE_IDS
