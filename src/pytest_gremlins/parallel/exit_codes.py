"""Exit codes shared between the gremlin bootstrap subprocess and the processes that score it."""

from __future__ import annotations

GREMLIN_COLLECTION_FAILED_EXIT_CODE = 71
"""Exit code the bootstrap uses when a mutant stopped the suite from loading.

Reported when the pytest session ran no tests because a conftest failed to import, a test module
failed to collect, or a selected node id no longer exists. pytest uses 0-5, 1 is a caught mutant
and 70 is the lightweight runner's abstention, so the parent can tell a mutant-caused load
failure from pytest-gremlins' own usage errors (exit 4).
"""

REWRITE_API_BROKEN_EXIT_CODE = 72
"""Exit code the bootstrap uses when pytest's private assertion-rewrite API changed (#617).

The bootstrap ends with ``os._exit`` while pytest may be capturing its stderr, so the explanation it writes
can be lost. A code of its own lets the parent state the cause itself. ``origin_finder`` spells the value
out, because it ships without pytest-gremlins on the path.
"""

COLLECTION_KILLING_TEST = '<collection>'
"""Killing-test label for a gremlin the suite caught before any test ran."""
