"""A mutant that stops the suite from loading is caught by the suite, in every execution mode (issue #550).

The v1.10.0 release run scored 147 of 681 attrs gremlins as ERROR because the mutant broke an import
in a conftest, a test module's collection, or a parametrize id; pytest exited 4 and ran nothing. The
baseline gate guarantees the unmutated suite loads, so the mutant did it, and the suite detected it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_TARGET_BREAKING_IMPORT = """
SLOTS = ('first', 'second')
LAST = SLOTS[2 - 1]


def last():
    return LAST
"""

_TEST_OF_LAST = """
import sample


def test_last():
    assert sample.last() == 'second'
"""

_TARGET_WITH_PARAMETRIZE_ID = """
LEVELS = (1 + 1,)


def double(level):
    return level * 2
"""

_TEST_PARAMETRIZED_BY_TARGET = """
import pytest
import sample


@pytest.mark.parametrize('level', sample.LEVELS)
def test_double(level):
    assert sample.double(level) == 4
"""

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=arithmetic',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_EXECUTION_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _verdicts(pytester: pytest.Pytester) -> list[tuple[str, str | None]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return sorted((entry['status'], entry.get('killing_test')) for entry in report['results'])


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
class DescribeMutantsThatBreakTheSuiteLoading:
    """Each way of failing to load is ZAPPED with the collection phase named as the killer."""

    def it_zaps_a_mutant_that_breaks_an_import_inside_conftest(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        conftest = pytester_with_markers.path / 'conftest.py'
        conftest.write_text(conftest.read_text() + '\nimport sample  # noqa: E402,F401\n')
        pytester_with_markers.makepyfile(sample=_TARGET_BREAKING_IMPORT)
        pytester_with_markers.makepyfile(test_sample=_TEST_OF_LAST)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_EXECUTION_MODES[mode])

        assert _verdicts(pytester_with_markers) == [('zapped', '<collection>')]

    def it_zaps_a_mutant_that_breaks_an_import_inside_a_test_module(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_BREAKING_IMPORT)
        pytester_with_markers.makepyfile(test_sample=_TEST_OF_LAST)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_EXECUTION_MODES[mode])

        assert _verdicts(pytester_with_markers) == [('zapped', '<collection>')]

    def it_zaps_a_mutant_that_changes_a_parametrize_id_of_the_selected_test(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_WITH_PARAMETRIZE_ID)
        pytester_with_markers.makepyfile(test_sample=_TEST_PARAMETRIZED_BY_TARGET)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_EXECUTION_MODES[mode])

        assert _verdicts(pytester_with_markers) == [('zapped', '<collection>'), ('zapped', 'unknown')]


@pytest.mark.medium
class DescribeRedBaselineStillSkipsMutation:
    """The baseline gate is what makes a load failure attributable to the mutant."""

    def it_skips_mutation_testing_when_the_unmutated_suite_does_not_collect(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_BREAKING_IMPORT)
        pytester_with_markers.makepyfile(test_sample='raise RuntimeError("baseline cannot collect")\n')

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS)

        assert 'skipping mutation testing' in result.stderr.str()
        assert not Path(pytester_with_markers.path, 'coverage', 'gremlins', 'gremlins.json').exists()
