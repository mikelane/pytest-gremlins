"""Mutation switching mechanism.

This module provides the mechanism for determining which gremlin (mutation)
is currently active. The active gremlin is controlled via the ACTIVE_GREMLIN
environment variable.
"""

from __future__ import annotations

import os


ACTIVE_GREMLIN_ENV_VAR = 'ACTIVE_GREMLIN'


def get_active_gremlin() -> str | None:
    """Get the currently active gremlin ID from the environment.

    Returns:
        The gremlin ID if ACTIVE_GREMLIN is set, None otherwise.
    """
    return os.environ.get(ACTIVE_GREMLIN_ENV_VAR)
