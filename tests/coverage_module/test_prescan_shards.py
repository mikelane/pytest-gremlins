"""Dividing the pre-scan's node ids into shards (issue #527)."""

from __future__ import annotations

import pytest

from pytest_gremlins.coverage.prescan_shards import split_into_shards


def _ids(file: str, count: int) -> list[str]:
    return [f'{file}::test_{index}' for index in range(count)]


@pytest.mark.small
class DescribeSplitIntoShards:
    def it_returns_one_shard_holding_every_id_for_a_count_of_one(self) -> None:
        node_ids = [*_ids('a.py', 2), *_ids('b.py', 1)]

        assert split_into_shards(node_ids, 1) == [node_ids]

    def it_returns_no_shards_for_no_node_ids(self) -> None:
        assert split_into_shards([], 4) == []

    def it_keeps_every_test_of_a_file_in_one_shard_in_its_original_order(self) -> None:
        node_ids = [*_ids('a.py', 3), *_ids('b.py', 3), *_ids('c.py', 3)]

        shards = split_into_shards(node_ids, 2)

        for file in ('a.py', 'b.py', 'c.py'):
            holding = [shard for shard in shards if any(i.startswith(f'{file}::') for i in shard)]
            assert len(holding) == 1
            assert [i for i in holding[0] if i.startswith(f'{file}::')] == _ids(file, 3)

    def it_places_each_id_in_exactly_one_shard(self) -> None:
        node_ids = [*_ids('a.py', 5), *_ids('b.py', 2), *_ids('c.py', 7), *_ids('d.py', 1)]

        shards = split_into_shards(node_ids, 3)

        assert sorted(i for shard in shards for i in shard) == sorted(node_ids)

    def it_gives_the_next_file_to_the_shard_with_the_fewest_tests_so_far(self) -> None:
        node_ids = [*_ids('big.py', 10), *_ids('mid.py', 6), *_ids('s1.py', 2), *_ids('s2.py', 2), *_ids('s3.py', 2)]

        shards = split_into_shards(node_ids, 2)

        assert sorted(len(shard) for shard in shards) == [10, 12]

    def it_uses_no_more_shards_than_there_are_files(self) -> None:
        node_ids = [*_ids('a.py', 4), *_ids('b.py', 4)]

        shards = split_into_shards(node_ids, 8)

        assert [len(shard) for shard in shards] == [4, 4]

    def it_orders_the_files_inside_a_shard_as_the_input_did(self) -> None:
        node_ids = [*_ids('a.py', 1), *_ids('b.py', 1), *_ids('c.py', 1)]

        shards = split_into_shards(node_ids, 1)

        assert shards == [['a.py::test_0', 'b.py::test_0', 'c.py::test_0']]

    def it_is_deterministic(self) -> None:
        node_ids = [*_ids('a.py', 3), *_ids('b.py', 3), *_ids('c.py', 3), *_ids('d.py', 3)]

        assert split_into_shards(node_ids, 3) == split_into_shards(node_ids, 3)

    def it_treats_a_parametrized_id_with_colons_in_its_parameters_as_part_of_its_file(self) -> None:
        node_ids = ['a.py::test_x[a::b]', 'a.py::test_x[c]', 'b.py::T::test_y']

        shards = split_into_shards(node_ids, 2)

        assert sorted(shards, key=len) == [['b.py::T::test_y'], ['a.py::test_x[a::b]', 'a.py::test_x[c]']]

    def it_treats_an_id_without_a_test_part_as_its_own_file(self) -> None:
        shards = split_into_shards(['tests/test_a.py', 'tests/test_b.py'], 2)

        assert sorted(shards) == [['tests/test_a.py'], ['tests/test_b.py']]
