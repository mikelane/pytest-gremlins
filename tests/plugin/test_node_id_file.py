"""Node ids travel in a file, not on the command line, so a large suite cannot overflow it (issue #485)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_gremlins.node_id_file import (
    NODE_IDS_FILE_OPTION,
    args_with_node_ids_from_file,
    command_with_node_ids_file,
    write_node_ids_file,
)

# The shape of the ids in the issue's report: long parametrized ids, 430 of them (53,818 characters).
REPORTED_NODE_IDS = [
    f'tests/unit/entities/test_entity_registry_{i // 20}.py'
    f'::test_entity_for_route_maps_registry_key_{i}[ExampleFacility-ExampleFacility]'
    for i in range(430)
]


@pytest.mark.medium
class DescribeWriteNodeIdsFile:
    def it_stores_the_node_ids_in_order(self, tmp_path: Path) -> None:
        path = write_node_ids_file(REPORTED_NODE_IDS, tmp_path)

        assert json.loads(path.read_text(encoding='utf-8')) == REPORTED_NODE_IDS

    def it_writes_the_file_inside_the_given_directory(self, tmp_path: Path) -> None:
        assert write_node_ids_file(['a.py::t'], tmp_path).parent == tmp_path

    def it_names_one_file_per_distinct_selection(self, tmp_path: Path) -> None:
        first = write_node_ids_file(['a.py::t1'], tmp_path)
        again = write_node_ids_file(['a.py::t1'], tmp_path)
        other = write_node_ids_file(['a.py::t2'], tmp_path)

        assert first == again
        assert first != other

    def it_distinguishes_the_same_ids_in_another_order(self, tmp_path: Path) -> None:
        assert write_node_ids_file(['a', 'b'], tmp_path) != write_node_ids_file(['b', 'a'], tmp_path)

    def it_leaves_no_temporary_files_behind(self, tmp_path: Path) -> None:
        path = write_node_ids_file(['a.py::t1'], tmp_path)

        assert list(tmp_path.iterdir()) == [path]

    def it_keeps_non_ascii_ids_intact(self, tmp_path: Path) -> None:
        node_ids = ['tests/test_x.py::test_café[☃]']

        path = write_node_ids_file(node_ids, tmp_path)

        assert json.loads(path.read_text(encoding='utf-8')) == node_ids


@pytest.mark.medium
class DescribeCommandWithNodeIdsFile:
    def it_keeps_every_node_id_off_the_command_line(self, tmp_path: Path) -> None:
        command = command_with_node_ids_file(['python', 'bootstrap.py', '-x'], REPORTED_NODE_IDS, tmp_path)

        assert not set(REPORTED_NODE_IDS) & set(command)
        assert len(' '.join(command)) < 32_767

    def it_names_the_file_holding_the_ids(self, tmp_path: Path) -> None:
        command = command_with_node_ids_file(['python'], REPORTED_NODE_IDS, tmp_path)

        option = command[-1]
        path = Path(option.removeprefix(f'{NODE_IDS_FILE_OPTION}='))
        assert json.loads(path.read_text(encoding='utf-8')) == REPORTED_NODE_IDS

    def it_keeps_the_base_command_unchanged(self, tmp_path: Path) -> None:
        base = ['python', 'bootstrap.py', '-x']

        command = command_with_node_ids_file(base, ['a.py::t'], tmp_path)

        assert command[:-1] == base
        assert base == ['python', 'bootstrap.py', '-x']

    def it_leaves_the_command_alone_when_there_are_no_node_ids(self, tmp_path: Path) -> None:
        assert command_with_node_ids_file(['python', '-x'], [], tmp_path) == ['python', '-x']
        assert list(tmp_path.iterdir()) == []

    def it_falls_back_to_the_command_line_without_a_directory(self) -> None:
        assert command_with_node_ids_file(['python'], ['a.py::t'], None) == ['python', 'a.py::t']


@pytest.mark.medium
class DescribeArgsWithNodeIdsFromFile:
    def it_appends_the_ids_after_the_remaining_arguments(self, tmp_path: Path) -> None:
        command = command_with_node_ids_file(['-x', '--tb=no'], ['a.py::t1', 'b.py::t2'], tmp_path)

        assert args_with_node_ids_from_file(command) == ['-x', '--tb=no', 'a.py::t1', 'b.py::t2']

    def it_removes_the_option_wherever_it_appears(self, tmp_path: Path) -> None:
        path = write_node_ids_file(['a.py::t1'], tmp_path)

        args = args_with_node_ids_from_file(['-x', f'{NODE_IDS_FILE_OPTION}={path}', '-q'])

        assert args == ['-x', '-q', 'a.py::t1']

    def it_returns_the_arguments_unchanged_without_the_option(self) -> None:
        assert args_with_node_ids_from_file(['-x', 'a.py::t']) == ['-x', 'a.py::t']

    def it_keeps_a_path_containing_equals_signs_and_spaces(self, tmp_path: Path) -> None:
        directory = tmp_path / 'dir with a=b'
        directory.mkdir()
        command = command_with_node_ids_file([], ['a.py::t1'], directory)

        assert args_with_node_ids_from_file(command) == ['a.py::t1']

    def it_raises_when_the_file_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(OSError, match=r'missing\.json'):
            args_with_node_ids_from_file([f'{NODE_IDS_FILE_OPTION}={tmp_path / "missing.json"}'])

    @pytest.mark.parametrize('content', ['not json', '{"a": 1}', '[1, 2]'], ids=['garbage', 'object', 'non-strings'])
    def it_raises_when_the_file_does_not_hold_a_list_of_strings(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / 'ids.json'
        path.write_text(content, encoding='utf-8')

        with pytest.raises(ValueError, match='node id'):
            args_with_node_ids_from_file([f'{NODE_IDS_FILE_OPTION}={path}'])
