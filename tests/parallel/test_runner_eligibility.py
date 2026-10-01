"""Tests for the lightweight-runner eligibility predicate.

The lightweight runner calls test callables directly, so it can only judge
tests that pytest would also run as a bare call: no fixtures, no
parametrization, no coroutines, no skip/xfail semantics.
"""

from __future__ import annotations

import textwrap

import pytest

from pytest_gremlins.parallel.runner_eligibility import is_lightweight_safe


def _collect_one(pytester: pytest.Pytester, source: str) -> pytest.Item:
    items = pytester.getitems(textwrap.dedent(source))
    return items[0]


@pytest.mark.medium
class DescribeIsLightweightSafe:
    """Only plain, fixture-free, synchronous, unparametrized tests are safe."""

    def it_accepts_a_plain_function(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            def test_plain():
                assert True
            """,
        )

        assert is_lightweight_safe(item) is True

    def it_accepts_a_method_on_a_plain_class(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            class TestThing:
                def test_method(self):
                    assert True
            """,
        )

        assert is_lightweight_safe(item) is True

    def it_rejects_a_test_requesting_a_fixture(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            def test_fixture(tmp_path):
                assert tmp_path
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_a_test_covered_by_a_conftest_autouse_fixture(self, pytester_with_markers: pytest.Pytester) -> None:
        existing = pytester_with_markers.path.joinpath('conftest.py').read_text()
        pytester_with_markers.makeconftest(
            existing
            + textwrap.dedent(
                """
                @pytest.fixture(autouse=True)
                def _always():
                    yield
                """
            )
        )
        item = _collect_one(
            pytester_with_markers,
            """
            def test_plain():
                assert True
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_a_parametrized_test(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            import pytest

            @pytest.mark.parametrize('n', [1, 2])
            def test_param(n):
                assert n
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_an_async_test(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            async def test_async():
                assert True
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_a_method_using_xunit_setup(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            class TestThing:
                def setup_method(self):
                    self.value = 1

                def test_method(self):
                    assert self.value
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_a_unittest_test_case(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            import unittest

            class TestThing(unittest.TestCase):
                def test_method(self):
                    self.assertTrue(True)
            """,
        )

        assert is_lightweight_safe(item) is False

    @pytest.mark.parametrize(
        'marker',
        ['skip', 'skipif(True, reason="x")', 'xfail', 'filterwarnings("error")'],
    )
    def it_rejects_a_test_with_a_marker_pytest_acts_on_around_the_call(
        self, pytester_with_markers: pytest.Pytester, marker: str
    ) -> None:
        item = _collect_one(
            pytester_with_markers,
            f"""
            import pytest

            @pytest.mark.{marker}
            def test_marked():
                assert True
            """,
        )

        assert is_lightweight_safe(item) is False

    def it_rejects_a_method_on_a_nested_class(self, pytester_with_markers: pytest.Pytester) -> None:
        item = _collect_one(
            pytester_with_markers,
            """
            class TestOuter:
                class TestInner:
                    def test_deep(self):
                        assert True
            """,
        )

        assert is_lightweight_safe(item) is False
