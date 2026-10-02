"""Exit codes shared between the gremlin bootstrap subprocess and the processes that score it."""

from __future__ import annotations

GREMLIN_COLLECTION_FAILED_EXIT_CODE = 71
"""Exit code the bootstrap uses when a mutant stopped the suite from loading.

Reported when the pytest session ran no tests because a conftest failed to import, a test module
failed to collect, or a selected node id no longer exists. pytest uses 0-5, 1 is a caught mutant
and 70 is the lightweight runner's abstention, so the parent can tell a mutant-caused load
failure from pytest-gremlins' own usage errors (exit 4).
"""

COLLECTION_KILLING_TEST = '<collection>'
"""Killing-test label for a gremlin the suite caught before any test ran."""
