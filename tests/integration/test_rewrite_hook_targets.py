"""Targets that pytest's assertion-rewrite hook serves are still instrumented (#603).

pytest installs its ``AssertionRewritingHook`` at the front of ``sys.meta_path`` while parsing the
command line. The gremlin finder is installed before ``pytest.main`` and so ends up behind it, which
left every module the hook claims (``python_files`` matches, ``conftest.py``) uncompiled by us, so its
gremlins could never be zapped.
"""

from __future__ import annotations

import re

import pytest

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_POSITIVE = """
def positive(n):
    return n > 0
"""

_HELPER_TESTS = """
from mypkg.core_impl import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_CONFTEST_WITH_TARGET = """
def positive(n):
    return n > 0
"""

_CONFTEST_TESTS = """
import conftest


def test_positive():
    assert conftest.positive(1)
    assert not conftest.positive(0)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _verdicts(output: str) -> tuple[int, int, int]:
    return _count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeRewriteHookTargets:
    """A target pytest would rewrite is instrumented anyway, so a test that catches its mutant zaps it."""

    def it_zaps_a_target_whose_file_name_matches_python_files(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src\npython_files = test_*.py *_impl.py\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core_impl.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_helper.py').write_text(_HELPER_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_zaps_a_conftest_target(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeconftest(_CONFTEST_WITH_TARGET)
        pytester_with_markers.mkdir('tests').joinpath('test_conftest_target.py').write_text(_CONFTEST_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=conftest.py')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)


_CONFTEST_ASSERTING_HELPER = """
def check_positive(n):
    assert n > 0
"""

_ASSERT_MESSAGE_TESTS = """
import pytest
import conftest


def test_message_names_the_value():
    with pytest.raises(AssertionError, match='-1'):
        conftest.check_positive(-1)


def test_accepts_a_positive_value():
    conftest.check_positive(1)
"""

_REGISTERING_CONFTEST = """
import pytest

pytest.register_assert_rewrite('helpers')
"""

_HELPER_PACKAGE = """
def check_positive(n):
    assert n > 0
"""

_HELPER_MESSAGE_TESTS = """
import pytest
from helpers import check_positive


def test_message_names_the_value():
    with pytest.raises(AssertionError, match='-1'):
        check_positive(-1)


def test_accepts_a_positive_value():
    check_positive(1)
"""


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeRewriteHookTargetAssertions:
    """A target pytest would rewrite keeps its rewritten assert messages under every gremlin.

    The ``n > 0`` to ``n >= 0`` gremlin still raises for ``-1`` with ``-1`` in pytest's rewritten message, so no
    test catches it and it must survive. Serving the target without assertion rewriting empties the message,
    the message test fails under every gremlin, and the survivor is reported ZAPPED.
    """

    def it_keeps_a_conftest_helpers_survivor_when_a_test_reads_its_assert_message(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeconftest(_CONFTEST_ASSERTING_HELPER)
        pytester_with_markers.mkdir('tests').joinpath('test_messages.py').write_text(_ASSERT_MESSAGE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=conftest.py')

        assert _verdicts(result.stdout.str()) == (1, 1, 0)

    def it_keeps_a_registered_helpers_survivor_when_a_test_reads_its_assert_message(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeconftest(_REGISTERING_CONFTEST)
        pytester_with_markers.makeini('[pytest]\npythonpath = src\n')
        package = pytester_with_markers.path / 'src' / 'helpers'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text(_HELPER_PACKAGE)
        pytester_with_markers.mkdir('tests').joinpath('test_messages.py').write_text(_HELPER_MESSAGE_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/helpers')

        assert _verdicts(result.stdout.str()) == (1, 1, 0)


_DEEP_BRANCHES = 470
_IMPORT_CHAIN_LENGTH = 40

_DEEP_TARGET_TESTS = """
import pytest

import mypkg.link_0
from mypkg.deep_impl import check_positive


def test_message_names_the_value():
    with pytest.raises(AssertionError, match='-1'):
        check_positive(-1)


def test_accepts_a_positive_value():
    check_positive(1)
"""


def _deep_target_source() -> str:
    branches = ''.join(f'    elif flags[{index}]:\n        return {index}\n' for index in range(1, _DEEP_BRANCHES))
    chain = f'def pick(flags):\n    if flags[0]:\n        return 0\n{branches}'
    return f'{chain}\n\ndef check_positive(n):\n    assert n > 0\n'


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeDeepRewriteHookTargetAssertions:
    """A deep target the rewrite hook serves keeps rewritten assert messages when specialization runs out of stack.

    The parent instruments a few hundred ``elif`` branches, and pytest's own rewriter walks them iteratively, but
    the recursive assert specialization raises ``RecursionError`` once the module is imported through a chain of
    imports. The loader then compiles the source with plain asserts, and the survivor is reported ZAPPED again.
    """

    def it_keeps_a_deep_targets_survivor_when_a_test_reads_its_assert_message(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src\npython_files = test_*.py *_impl.py\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('deep_impl.py').write_text(_deep_target_source())
        for link in range(_IMPORT_CHAIN_LENGTH):
            package.joinpath(f'link_{link}.py').write_text(f'import mypkg.link_{link + 1}\n')
        package.joinpath(f'link_{_IMPORT_CHAIN_LENGTH}.py').write_text('import mypkg.deep_impl\n')
        pytester_with_markers.mkdir('tests').joinpath('test_messages.py').write_text(_DEEP_TARGET_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg/deep_impl.py')

        assert _verdicts(result.stdout.str()) == (1, 1, 0)
