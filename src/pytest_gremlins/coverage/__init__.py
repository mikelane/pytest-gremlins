"""Coverage-guided test selection for mutation testing.

This module provides the second pillar of pytest-gremlins' speed strategy:
Coverage-Guided Test Selection. Instead of running all tests against each
gremlin, we only run tests that actually cover the mutated code.

The key insight:
    coverage_map = {
        "src/auth.py:42": ["test_login_success", "test_login_failure"],
        "src/shipping.py:17": ["test_calculate_shipping"],
    }

    # Gremlin in auth.py:42 -> run 2 tests, not 500

This provides 10-1000x reduction in test executions.

Exports:
    CoverageMap: Maps source locations to test functions
    CoverageCollector: Collects coverage data per-test
    TestSelector: Selects tests based on gremlin location
"""

from __future__ import annotations

from pytest_gremlins.coverage.collector import CoverageCollector
from pytest_gremlins.coverage.mapper import CoverageMap
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.coverage.selector import TestSelector


__all__ = ['CoverageCollector', 'CoverageMap', 'PrioritizedSelector', 'TestSelector']
