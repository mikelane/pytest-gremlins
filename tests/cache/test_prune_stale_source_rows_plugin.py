"""The plugin prunes rows stranded by an edited source file at run start (#930)."""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.hasher import ContentHasher

if TYPE_CHECKING:
    from pathlib import Path

FIRST_SOURCE = 'def add(a, b):\n    return a + b\n'
EDITED_SOURCE = 'def add(a, b):\n    return a + b + 0\n'
TEST_SOURCE = 'from src_module import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'


def _stored_keys(project: Path) -> list[str]:
    with sqlite3.connect(project / '.gremlins_cache' / 'results.db') as conn:
        keys = [row[0] for row in conn.execute('SELECT cache_key FROM results')]
    conn.close()
    return keys


def _hash_of(project: Path, module: str) -> str:
    return ContentHasher().hash_string((project / f'{module}.py').read_text())


def _keys_under_source_hash(project: Path, source_hash: str) -> list[str]:
    return [key for key in _stored_keys(project) if f':{source_hash}:' in key]


@pytest.mark.medium
class DescribePruningThroughThePlugin:
    @pytest.mark.parametrize(
        'extra_args',
        [(), ('--gremlin-parallel', '--gremlin-workers=2'), ('-n', '2')],
        ids=['serial', 'gremlin-parallel', 'xdist'],
    )
    def it_leaves_no_row_under_the_old_source_hash_after_an_edit(
        self, pytester_with_markers: pytest.Pytester, extra_args: tuple[str, ...]
    ) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(src_module=FIRST_SOURCE, test_module=TEST_SOURCE)
        args = ('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache', *extra_args)
        pytester.runpytest(*args)
        first_hash = _hash_of(pytester.path, 'src_module')
        assert _keys_under_source_hash(pytester.path, first_hash)

        pytester.makepyfile(src_module=EDITED_SOURCE)
        pytester.runpytest(*args)

        assert _keys_under_source_hash(pytester.path, first_hash) == []
        assert _keys_under_source_hash(pytester.path, _hash_of(pytester.path, 'src_module'))

    def it_leaves_only_current_hash_rows_after_an_edit_with_clear_cache(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(src_module=FIRST_SOURCE, test_module=TEST_SOURCE)
        args = ('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        pytester.runpytest(*args)
        first_hash = _hash_of(pytester.path, 'src_module')
        pytester.makepyfile(src_module=EDITED_SOURCE)

        result = pytester.runpytest(*args, '--gremlin-clear-cache')

        current_hash = _hash_of(pytester.path, 'src_module')
        assert result.ret == 0
        assert _keys_under_source_hash(pytester.path, first_hash) == []
        assert _keys_under_source_hash(pytester.path, current_hash) == _stored_keys(pytester.path)
        assert _stored_keys(pytester.path)

    def it_hits_every_row_on_an_unchanged_third_run(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(src_module=FIRST_SOURCE, test_module=TEST_SOURCE)
        args = ('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache')
        pytester.runpytest(*args)
        pytester.makepyfile(src_module=EDITED_SOURCE)
        pytester.runpytest(*args)
        rows_before = sorted(_stored_keys(pytester.path))

        result = pytester.runpytest(*args)

        result.stdout.fnmatch_lines(['*cache hit*'])
        result.stdout.no_fnmatch_line('*cache miss*')
        assert sorted(_stored_keys(pytester.path)) == rows_before

    def it_keeps_rows_of_an_unedited_file_when_another_file_changes(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(src_module=FIRST_SOURCE, other_module=FIRST_SOURCE, test_module=TEST_SOURCE)
        pytester.makepyfile(
            test_other='from other_module import add\n\n\ndef test_other():\n    assert add(1, 2) == 3\n'
        )
        args = ('--gremlins', '--gremlin-targets=src_module.py,other_module.py', '--gremlin-cache')
        pytester.runpytest(*args)
        other_rows = sorted(key for key in _stored_keys(pytester.path) if key.startswith('other_module_'))
        assert other_rows

        pytester.makepyfile(src_module=EDITED_SOURCE)
        pytester.runpytest(*args)

        assert set(other_rows) <= set(_stored_keys(pytester.path))


PID_LOGGING_CONFTEST = """
import os
from pathlib import Path

from pytest_gremlins.cache.incremental import IncrementalCache

for _name in ('prune_stale_sources', 'cache_result_deferred', 'cache_result', 'flush'):
    def _wrap(original=getattr(IncrementalCache, _name), name=_name):
        def wrapper(self, *args, **kwargs):
            with Path('cache_calls.log').open('a') as log:
                log.write(f'{name} {os.getpid()}\\n')
            return original(self, *args, **kwargs)
        return wrapper
    setattr(IncrementalCache, _name, _wrap())
"""


@pytest.mark.medium
class DescribePruningStaysInTheController:
    def it_touches_the_cache_only_from_the_controller_process(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makeconftest(PID_LOGGING_CONFTEST)
        pytester.makepyfile(src_module=FIRST_SOURCE, test_module=TEST_SOURCE)

        pytester.runpytest('--gremlins', '--gremlin-targets=src_module.py', '--gremlin-cache', '-n', '2')

        calls = (pytester.path / 'cache_calls.log').read_text().splitlines()
        assert any(call.startswith('prune_stale_sources ') for call in calls)
        assert {call.split()[1] for call in calls} == {str(os.getpid())}
