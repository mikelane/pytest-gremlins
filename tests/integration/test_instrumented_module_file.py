"""An instrumented module keeps the ``__file__`` of the source it was built from."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

_TARGET = """
from pathlib import Path

LIMIT = int((Path(__file__).parent / 'limit.txt').read_text())


def classify(n):
    if n > LIMIT:
        return 'big'
    return 'small'
"""

_TESTS = """
import os

import sample

LOG = '__LOG__'


def test_classify():
    row = (os.environ.get('ACTIVE_GREMLIN', 'NONE'), sample.__file__, sample.__spec__.origin)
    with open(LOG, 'a') as handle:
        handle.write('\\t'.join(row) + '\\n')
    assert sample.classify(11) == 'big'
    assert sample.classify(10) == 'small'
"""

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Timeout', 'Error')}


def _mutant_rows(log: Path) -> list[list[str]]:
    rows = [line.split('\t') for line in log.read_text().splitlines()]
    return [row for row in rows if row[0] != 'NONE']


@pytest.mark.medium
class DescribeInstrumentedModuleFile:
    """A target that locates data through ``Path(__file__)`` at import is mutation-tested like any other."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_scores_every_mutant_instead_of_erroring(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        log = pytester_with_markers.path / 'ran.log'
        pytester_with_markers.path.joinpath('limit.txt').write_text('10')
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TESTS.replace('__LOG__', log.as_posix()))

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
            *_EXECUTION_MODES[mode],
        )
        verdicts = _verdicts(result.stdout.str())

        assert verdicts['Error'] == 0
        assert verdicts['Zapped'] > 0

    def it_sets_file_and_origin_to_the_source_path(self, pytester_with_markers: pytest.Pytester) -> None:
        log = pytester_with_markers.path / 'ran.log'
        pytester_with_markers.path.joinpath('limit.txt').write_text('10')
        target = pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TESTS.replace('__LOG__', log.as_posix()))

        pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider'
        )

        rows = _mutant_rows(log)
        assert rows
        assert {(file, origin) for _, file, origin in rows} == {(str(target), str(target))}

    def it_keeps_the_path_a_symlinked_target_is_imported_through(self, pytester_with_markers: pytest.Pytester) -> None:
        log = pytester_with_markers.path / 'ran.log'
        pytester_with_markers.path.joinpath('limit.txt').write_text('10')
        real = pytester_with_markers.mkdir('real') / 'sample_impl.py'
        real.write_text(_TARGET)
        target = pytester_with_markers.path / 'sample.py'
        target.symlink_to(real)
        pytester_with_markers.makepyfile(test_sample=_TESTS.replace('__LOG__', log.as_posix()))

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider'
        )

        assert _verdicts(result.stdout.str())['Error'] == 0
        assert {file for _, file, _ in _mutant_rows(log)} == {str(target)}
