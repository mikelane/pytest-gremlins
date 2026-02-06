"""Integration tests for boolean mutations in class attribute defaults.

Regression tests for GitHub issue #91: boolean mutations in dataclass
field defaults are incorrectly reported as surviving gremlins.

The root cause: coverage.py's dynamic context feature records class-level code
(executed at import time) under the empty context. The plugin's coverage query
excludes the empty context, so class attribute defaults get zero covering tests.
With zero covering tests, the plugin marks the gremlin as "survived" without
ever actually testing the mutation.

These tests verify the end-to-end behavior using pytester. They create a
dataclass with boolean defaults and tests that depend on those defaults,
then verify that the boolean mutations are correctly reported as ZAPPED.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def pytester_with_conftest(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance with conftest that registers small marker for nested tests."""
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
"""
    )
    return pytester


@pytest.mark.medium
class TestBooleanClassDefaultBug:
    """Reproduce issue #91: boolean mutations in dataclass defaults falsely survive."""

    def test_false_to_true_mutation_in_dataclass_default_is_zapped(self, pytester_with_conftest: pytest.Pytester):
        """A False->True mutation in a dataclass default is zapped when tests depend on it.

        This reproduces the exact scenario from issue #91: a dataclass field
        `last: bool = False` should be detected as zapped because tests create
        instances relying on the default value.
        """
        pytester_with_conftest.makepyfile(
            target_module="""
from dataclasses import dataclass

@dataclass
class Addr:
    name: str = ''
    last: bool = False

def make_default_addr():
    return Addr()
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import Addr, make_default_addr

def test_default_addr_last_is_false():
    addr = Addr()
    assert addr.last is False

def test_make_default_addr_last_is_false():
    addr = make_default_addr()
    assert addr.last is False

def test_explicit_last_true():
    addr = Addr(last=True)
    assert addr.last is True
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-operators=boolean',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=3)
        output = result.stdout.str()

        # The False->True mutation on `last: bool = False` MUST be zapped
        # because test_default_addr_last_is_false asserts `addr.last is False`
        assert 'Zapped:' in output
        match = re.search(r'Zapped: (\d+)', output)
        assert match is not None, f'Could not find Zapped count in output:\n{output}'
        zapped_count = int(match.group(1))
        assert zapped_count >= 1, 'Expected the False->True boolean gremlin to be zapped, got 0 zapped'

        # Specifically: the False->True mutation must NOT appear as a survivor
        survived_match = re.search(r'Survived: (\d+)', output)
        if survived_match:
            survived_count = int(survived_match.group(1))
            # If there are survivors, none should be the False->True boolean mutation
            if survived_count > 0 and 'False' in output and 'True' in output:
                assert 'False to True' not in output.split('Top surviving gremlins:')[-1], (
                    'False->True boolean mutation in dataclass default falsely reported as surviving'
                )

    def test_true_to_false_mutation_in_dataclass_default_is_zapped(self, pytester_with_conftest: pytest.Pytester):
        """A True->False mutation in a dataclass default is zapped when tests depend on it."""
        pytester_with_conftest.makepyfile(
            target_module="""
from dataclasses import dataclass

@dataclass
class Range:
    start: int = 0
    from0: bool = True

def make_default_range():
    return Range()
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import Range, make_default_range

def test_default_range_from0_is_true():
    r = Range()
    assert r.from0 is True

def test_make_default_range_from0_is_true():
    r = make_default_range()
    assert r.from0 is True
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-operators=boolean',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=2)
        output = result.stdout.str()

        assert 'Zapped:' in output
        match = re.search(r'Zapped: (\d+)', output)
        assert match is not None, f'Could not find Zapped count in output:\n{output}'
        zapped_count = int(match.group(1))
        assert zapped_count >= 1, 'Expected the True->False boolean gremlin to be zapped, got 0 zapped'

    def test_both_boolean_defaults_in_same_class_are_zapped(self, pytester_with_conftest: pytest.Pytester):
        """Multiple boolean defaults in the same dataclass are all correctly tested."""
        pytester_with_conftest.makepyfile(
            target_module="""
from dataclasses import dataclass

@dataclass
class Config:
    enabled: bool = True
    debug: bool = False
"""
        )
        pytester_with_conftest.makepyfile(
            test_target="""
from target_module import Config

def test_default_config_enabled_is_true():
    config = Config()
    assert config.enabled is True

def test_default_config_debug_is_false():
    config = Config()
    assert config.debug is False
"""
        )

        result = pytester_with_conftest.runpytest(
            '--gremlins',
            '--gremlin-operators=boolean',
            '--gremlin-targets=target_module.py',
            '-v',
        )
        result.assert_outcomes(passed=2)
        output = result.stdout.str()

        # Both boolean gremlins should be zapped
        match = re.search(r'Zapped: (\d+)', output)
        assert match is not None, f'Could not find Zapped count in output:\n{output}'
        zapped_count = int(match.group(1))
        assert zapped_count == 2, f'Expected both boolean gremlins to be zapped, got {zapped_count}'

        survived_match = re.search(r'Survived: (\d+)', output)
        if survived_match:
            survived_count = int(survived_match.group(1))
            assert survived_count == 0, f'Expected 0 survivors, got {survived_count}. Output:\n{output}'
