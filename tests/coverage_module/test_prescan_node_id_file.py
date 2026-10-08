"""The coverage pre-scan keeps node ids off its command line and survives a failed launch (issue #485).

``subprocess.run`` is mocked throughout, so these run on every OS: the invariant is about what the command
holds, not about what a given OS would have refused.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import warnings

import pytest

from pytest_gremlins.node_id_file import NODE_IDS_FILE_OPTION
from pytest_gremlins.plugin import (
    CoveragePrescanLaunchError,
    CoveragePrescanTimeoutError,
    GremlinSession,
    _collect_coverage,
    _run_tests_with_coverage,
)

WINDOWS_MAX_CMDLINE = 32_767

# The shape of the ids in the issue's report: 430 of them, 53,818 characters once joined.
REPORTED_NODE_IDS = [
    f'tests/unit/entities/test_entity_registry_{i // 20}.py'
    f'::test_entity_for_route_maps_registry_key_{i}[ExampleFacility-ExampleFacility]'
    for i in range(430)
]


class _PrescanSpy:
    """Stands in for ``subprocess.run``, keeping the command and what the node ids file held at that moment."""

    def __init__(self) -> None:
        self.command: list[str] = []
        self.node_ids_file: Path | None = None
        self.node_ids: list[str] = []

    def __call__(self, command: list[str], **_kwargs: object) -> None:
        self.command = list(command)
        option = next((argument for argument in command if argument.startswith(f'{NODE_IDS_FILE_OPTION}=')), None)
        if option is not None:
            self.node_ids_file = Path(option.split('=', 1)[1])
            self.node_ids = json.loads(self.node_ids_file.read_text(encoding='utf-8'))


@pytest.fixture
def spy() -> _PrescanSpy:
    return _PrescanSpy()


@pytest.mark.medium
class DescribePrescanNodeIdsFile:
    def it_keeps_every_node_id_off_the_command_line(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert not set(REPORTED_NODE_IDS) & set(spy.command)

    def it_keeps_the_command_within_the_windows_limit(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert len(' '.join(spy.command)) < WINDOWS_MAX_CMDLINE

    def it_gives_the_launcher_every_node_id_in_order(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert spy.node_ids == REPORTED_NODE_IDS

    def it_runs_the_launcher_under_coverage_instead_of_pytest_itself(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        run_index = spy.command.index('run')
        assert spy.command[run_index + 2 : run_index + 4] == ['-m', 'pytest_gremlins.coverage.prescan_main']

    def it_keeps_the_context_plugin_and_disables_the_gremlins_plugin(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert spy.command[spy.command.index('-p') : spy.command.index('-p') + 4] == [
            '-p',
            'pytest_gremlins.coverage.subprocess_bootstrap',
            '-p',
            'no:gremlins',
        ]

    def it_removes_the_node_ids_file_afterwards(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert spy.node_ids_file is not None
        assert not spy.node_ids_file.exists()
        assert not spy.node_ids_file.parent.exists()

    def it_puts_no_option_on_the_command_for_an_empty_suite(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=spy):
            _run_tests_with_coverage([], tmp_path)

        assert spy.node_ids_file is None

    def it_removes_the_node_ids_file_when_the_pre_scan_times_out(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        def time_out(command: list[str], **kwargs: object) -> None:
            spy(command, **kwargs)
            raise subprocess.TimeoutExpired(command, 1)

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=time_out),
            pytest.raises(CoveragePrescanTimeoutError),
        ):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path, timeout=1)

        assert spy.node_ids_file is not None
        assert not spy.node_ids_file.parent.exists()


@pytest.mark.medium
class DescribePrescanLaunchFailure:
    """A pre-scan that cannot be started degrades to 'no coverage' with a warning naming the cause."""

    LAUNCH_ERROR = OSError(206, 'The filename or extension is too long')

    def it_raises_a_launch_error_naming_the_cause(self, tmp_path: Path) -> None:
        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=self.LAUNCH_ERROR),
            pytest.raises(CoveragePrescanLaunchError, match='too long'),
        ):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

    def it_removes_the_coveragerc_and_the_node_ids_file(self, tmp_path: Path, spy: _PrescanSpy) -> None:
        def fail_to_start(command: list[str], **kwargs: object) -> None:
            spy(command, **kwargs)
            raise self.LAUNCH_ERROR

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=fail_to_start),
            pytest.raises(CoveragePrescanLaunchError),
        ):
            _run_tests_with_coverage(REPORTED_NODE_IDS, tmp_path)

        assert not (tmp_path / '.coveragerc.gremlins').exists()
        assert spy.node_ids_file is not None
        assert not spy.node_ids_file.parent.exists()

    def it_does_not_escape_the_coverage_collection(self, tmp_path: Path) -> None:
        session = GremlinSession(enabled=True)
        session.test_node_ids = {node_id: node_id for node_id in REPORTED_NODE_IDS}

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=self.LAUNCH_ERROR),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            _collect_coverage(session, tmp_path)

        assert session.test_selector is not None
        assert [str(warning.message) for warning in caught if issubclass(warning.category, UserWarning)] == [
            'pytest-gremlins: the coverage pre-scan could not be started '
            '([Errno 206] The filename or extension is too long); coverage-guided test selection disabled',
        ]

    def it_does_not_also_claim_that_no_data_was_recorded(self, tmp_path: Path) -> None:
        session = GremlinSession(enabled=True)

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=self.LAUNCH_ERROR),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            _collect_coverage(session, tmp_path)

        assert 'returned no data' not in ' '.join(str(warning.message) for warning in caught)
