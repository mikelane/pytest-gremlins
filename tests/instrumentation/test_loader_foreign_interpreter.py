"""A tree pickled by one Python cannot always be unpickled by another (#604 adversarial QA).

The spawn hook puts the gremlin finder into every interpreter a test starts, including one of a different Python
version (``python3.11 -c 'import target'`` from a suite running on 3.14). ``ast`` node constructors change
between versions (3.12 added ``type_params``), so unpickling the shipped tree raises ``TypeError`` there. The
loader must fall back to the shipped source, as it already does for a tree too deep to unpickle, instead of
failing the import: a failed import fails the test only under a gremlin, which reports a false ZAPPED.
"""

from __future__ import annotations

import ast
import base64
import importlib.machinery
import pickle
from types import ModuleType

import pytest

from pytest_gremlins.instrumentation.origin_finder import GremlinLoader

SOURCE = 'def f():\n    return 1\n'
_TOO_MANY_FIELDS = 8


class _TreeFromAnotherPython:
    """Unpickles the way a tree from a newer Python does in 3.11: its constructor rejects the field count."""

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        return (ast.FunctionDef, tuple(range(_TOO_MANY_FIELDS)))


def _foreign_tree() -> str:
    return base64.b64encode(pickle.dumps(_TreeFromAnotherPython())).decode('ascii')


@pytest.mark.small
class DescribeGremlinLoaderWithATreeFromAnotherPython:
    """The loader serves the shipped source when this interpreter cannot rebuild the shipped tree."""

    def it_falls_back_to_the_shipped_source(self) -> None:
        module = ModuleType('foreign_mod')
        module.__spec__ = importlib.machinery.ModuleSpec('foreign_mod', None, origin='foreign_mod.py')

        GremlinLoader(_foreign_tree(), source=SOURCE).exec_module(module)

        assert module.f() == 1
