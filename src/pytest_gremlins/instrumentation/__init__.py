"""Instrumentation module for mutation switching.

This module contains the core components for instrumenting Python source code
with mutation switching capabilities.

The mutation switching architecture is the key speed optimization in pytest-gremlins.
Instead of modifying files on disk for each mutation, we instrument the code once
with all mutations embedded, and toggle them via an environment variable.

Example usage:
    >>> source = '''
    ... def is_adult(age):
    ...     return age >= 18
    ... '''
    >>> gremlins, tree = transform_source(source, 'example.py')
    >>> len(gremlins)  # Two mutations: >= to >, and >= to <
    2

The transformed code will execute the original logic when __gremlin_active__ is None,
or execute the mutation when __gremlin_active__ matches a gremlin's ID.
"""

from __future__ import annotations

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR, get_active_gremlin
from pytest_gremlins.instrumentation.transformer import transform_source


__all__ = [
    'ACTIVE_GREMLIN_ENV_VAR',
    'Gremlin',
    'get_active_gremlin',
    'transform_source',
]
