"""Integration tests for code that runs in a ``multiprocessing`` spawn child (#604).

A ``spawn`` child is a fresh interpreter: it never inherits the gremlin import finder that the bootstrap
installed in its parent, so before the fix it ran the original code and every gremlin only that child
exercised came back SURVIVED even though the tests catch it.
"""

from __future__ import annotations

import pytest

_TARGET = """\
def double(value):
    return value * 2
"""

# ``double(0)`` runs in the parent so coverage maps the gremlins to this test, but it is blind to the
# mutations (0 * 2 == 0 / 2 == 0). Only the spawn child's ``double(3)`` can tell the original from a gremlin.
_TEST = """\
import multiprocessing

from target import double


def test_double_in_spawn_child():
    assert double(0) == 0
    with multiprocessing.get_context('spawn').Pool(1) as pool:
        assert pool.apply(double, (3,)) == 6
"""

RUNNER_OPTIONS = [
    pytest.param([], id='sequential'),
    pytest.param(['--gremlin-parallel', '--gremlin-workers=2'], id='worker-pool'),
    pytest.param(['--gremlin-batch', '--gremlin-batch-size=2'], id='batch'),
]


@pytest.mark.medium
class DescribeSpawnChildren:
    """A gremlin only a ``spawn`` child exercises is judged against the instrumented code."""

    @pytest.mark.parametrize('runner_options', RUNNER_OPTIONS)
    def it_zaps_a_gremlin_only_a_spawn_child_exercises(
        self, pytester_with_markers: pytest.Pytester, runner_options: list[str]
    ) -> None:
        pytester_with_markers.makepyfile(target=_TARGET)
        pytester_with_markers.makepyfile(test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', *runner_options
        )

        result.stdout.fnmatch_lines(['*Zapped: 2 gremlins (100%)*'])
