"""A suite whose node ids alone exceed Windows' 32,767 character command line is mutation-tested (issue #485).

Before the ids moved into a file, the coverage pre-scan, every gremlin's test command and the timeout
confirmation put every node id on the command line, so a large suite crashed with ``WinError 206`` on
Windows. These tests build such a suite and run it in each execution mode in a real child process; the
child must finish, run the tests that cover each mutant and score every mutant correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

WINDOWS_MAX_CMDLINE = 32_767
TEST_FILE_COUNT = 2
TESTS_PER_FILE = 250
THRESHOLD = 10
TEST_NAME = 'test_classify_returns_the_registered_size_for_the_sample_value_{value:04d}_in_the_catalogue'

# Only the test for the value that equals the threshold can tell ``>`` from ``>=``, so a ``>=`` mutant
# is zapped only if that test is among the node ids that reached pytest.
_TARGET = f"""
def classify(n):
    if n > {THRESHOLD}:
        return 'big'
    return 'small'


def never_called(n):
    return n > 1
"""

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}

# classify is covered by every test and is zapped; never_called is covered by none, so its mutants fall
# back to the whole suite, run it, and honestly survive.
_EXPECTED_VERDICTS = [
    (2, '> to <', 'zapped'),
    (2, '> to >=', 'zapped'),
    (8, '> to <', 'survived'),
    (8, '> to >=', 'survived'),
]


def _test_file_source(file_index: int) -> str:
    first = file_index * TESTS_PER_FILE
    functions = ''.join(
        f'\n\ndef {TEST_NAME.format(value=value)}():\n'
        f'    assert sample.classify({value}) == {"big" if value > THRESHOLD else "small"!r}\n'
        for value in range(first, first + TESTS_PER_FILE)
    )
    return f'import sample\n{functions}'


def _write_large_suite(pytester: pytest.Pytester) -> list[str]:
    pytester.makepyfile(sample=_TARGET)
    node_ids: list[str] = []
    for file_index in range(TEST_FILE_COUNT):
        name = f'test_sizes_{file_index}'
        pytester.makepyfile(**{name: _test_file_source(file_index)})
        first = file_index * TESTS_PER_FILE
        node_ids.extend(f'{name}.py::{TEST_NAME.format(value=value)}' for value in range(first, first + TESTS_PER_FILE))
    return node_ids


def _verdicts(pytester: pytest.Pytester) -> list[tuple[int, str, str]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text(encoding='utf-8'))
    return sorted((entry['line_number'], entry['description'], entry['status']) for entry in report['results'])


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeLargeSuiteNodeIds:
    """The old command lines for this suite were well over the Windows limit."""

    def it_completes_and_scores_every_mutant_correctly(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        node_ids = _write_large_suite(pytester_with_markers)
        assert len(' '.join(node_ids)) > 1.5 * WINDOWS_MAX_CMDLINE

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        assert 'WinError' not in result.stdout.str() + result.stderr.str()
        assert _verdicts(pytester_with_markers) == _EXPECTED_VERDICTS
