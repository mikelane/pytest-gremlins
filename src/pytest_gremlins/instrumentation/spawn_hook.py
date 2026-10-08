"""A ``sitecustomize`` hook that gives interpreters started by the test run the gremlin import finder (#604).

A child started with the ``multiprocessing`` ``spawn`` (or ``forkserver``) method is a fresh interpreter. It never
inherits the finder the bootstrap installed in its parent, so it ran the original code and every gremlin that only
the child exercised came back SURVIVED even though the tests catch it.

Python imports ``sitecustomize`` at startup from the first ``sys.path`` entry that has one, and ``PYTHONPATH``
entries come before ``site-packages``. A runner therefore writes the hook into a directory of its own (so only
``sitecustomize`` becomes importable, never the bootstrap or ``sources.json`` next to it) and prepends that
directory to ``PYTHONPATH``, next to ``PYTEST_GREMLINS_SOURCES_FILE`` and ``ACTIVE_GREMLIN``, all of which a
spawned child inherits. A ``.pth`` file would not do: those are processed only in site directories.

The hook shadows any ``sitecustomize`` of the user's (``coverage`` relies on one), so it finds and runs the next
one itself.

The hook serves only an interpreter of the same implementation and ``(major, minor)`` version as the one that
wrote the sources: the shipped ASTs are pickled, and another version cannot read them (``TypeError`` before
3.12 reads a 3.13+ tree, ``DeprecationWarning`` the other way round). A test that starts such an interpreter
(``subprocess.run(['python3.11', ...])``) therefore runs the original code in it, silently, as the control run
does: at worst a false SURVIVED, never a false ZAPPED.

Limitation: an interpreter started with ``-E``, ``-I`` or ``-S`` ignores ``PYTHONPATH`` or skips ``site``, so a
child started that way still runs the original code. That is not fixed here.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import inspect
import os
from pathlib import Path
import sys

from pytest_gremlins.instrumentation import origin_finder

SOURCES_FILE_ENV_VAR = 'PYTEST_GREMLINS_SOURCES_FILE'
SPAWN_HOOK_DIRNAME = 'spawn_hook'

# The hook cannot import pytest-gremlins (the child may not have it on its path, and startup must stay cheap),
# so it embeds the finder's source exactly as the bootstrap does.
_HOOK_FIRST_LINE = (
    '"""pytest-gremlins: serve instrumented sources to this interpreter, then run the next sitecustomize."""'
)

_SPAWN_HOOK_TEMPLATE = '''\
__HOOK_FIRST_LINE_TEXT__

import importlib.machinery
import importlib.util
import json
import os
import sys
import traceback

__ORIGIN_FINDER_SOURCE__


_PRODUCER_IMPLEMENTATION = __PRODUCER_IMPLEMENTATION__
_PRODUCER_VERSION = __PRODUCER_VERSION__


def _is_producer_interpreter():
    return (sys.implementation.name, tuple(sys.version_info[:2])) == (_PRODUCER_IMPLEMENTATION, _PRODUCER_VERSION)


def _install_gremlin_finder():
    sources_file = os.environ.get('__SOURCES_FILE_ENV_VAR__')
    if not sources_file:
        return
    if not _is_producer_interpreter():
        # The shipped ASTs are pickled and cannot be read by another implementation or minor version. Staying
        # silent leaves this interpreter running the original code, as the control run does.
        return
    try:
        with open(sources_file, encoding='utf-8') as sources:
            install(json.load(sources))
    except Exception:
        # Never take the interpreter down: that would hide the user's tests behind a startup failure. Say so
        # loudly instead, because this interpreter now runs the original code.
        print(
            'pytest-gremlins: could not install the import finder in this interpreter (%s); '
            'it runs the original, unmutated code.' % sources_file,
            file=sys.stderr,
        )
        traceback.print_exc()


def _real_directory(entry):
    return os.path.normcase(os.path.realpath(entry or os.getcwd()))


def _is_gremlin_hook(spec):
    try:
        with open(spec.origin, encoding='utf-8') as candidate:
            return candidate.readline().startswith(__HOOK_FIRST_LINE__)
    except (OSError, ValueError, TypeError):
        return False


def _find_next_sitecustomize():
    """Find the sitecustomize this one shadows, looking past the hooks of any enclosing gremlin runs.

    Each enclosing run leaves its own hook directory on PYTHONPATH. Every hook does the same job, so chaining to
    one would only make the two hand control back and forth until the stack ran out.
    """
    skipped = {_real_directory(os.path.dirname(__file__))}
    while True:
        others = [entry for entry in sys.path if _real_directory(entry) not in skipped]
        spec = importlib.machinery.PathFinder.find_spec('sitecustomize', others)
        if spec is None or spec.loader is None or not _is_gremlin_hook(spec):
            return spec
        hook_directory = _real_directory(os.path.dirname(spec.origin))
        if hook_directory in skipped:
            return None
        skipped.add(hook_directory)


def _run_next_sitecustomize():
    """Run the sitecustomize this one shadows, as Python would have if the hook were not first on the path."""
    spec = _find_next_sitecustomize()
    if spec is None:
        return
    own_module = sys.modules.get(__name__)
    module = importlib.util.module_from_spec(spec)
    sys.modules['sitecustomize'] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Report it the way site.py does and carry on: the user's own sitecustomize failing is theirs to fix.
        if own_module is not None:
            sys.modules['sitecustomize'] = own_module
        print('Error in sitecustomize; set PYTHONVERBOSE for traceback:', file=sys.stderr)
        traceback.print_exc()


_install_gremlin_finder()
_run_next_sitecustomize()
'''


def get_spawn_hook_script(
    implementation: str = sys.implementation.name,
    version: tuple[int, int] = (sys.version_info.major, sys.version_info.minor),
) -> str:
    """Return the source of the ``sitecustomize.py`` that installs the finder in a fresh interpreter.

    The hook installs the finder only in an interpreter of the given ``implementation`` and ``(major, minor)``
    ``version``, which default to this interpreter's: the one that pickles the sources the hook serves.
    """
    return (
        _SPAWN_HOOK_TEMPLATE.replace('__HOOK_FIRST_LINE_TEXT__', _HOOK_FIRST_LINE)
        .replace('__HOOK_FIRST_LINE__', repr(_HOOK_FIRST_LINE))
        .replace('__SOURCES_FILE_ENV_VAR__', SOURCES_FILE_ENV_VAR)
        .replace('__PRODUCER_IMPLEMENTATION__', repr(implementation))
        .replace('__PRODUCER_VERSION__', repr(tuple(version)))
        .replace('__ORIGIN_FINDER_SOURCE__', inspect.getsource(origin_finder))
    )


def write_spawn_hook(
    instrumented_dir: Path,
    implementation: str = sys.implementation.name,
    version: tuple[int, int] = (sys.version_info.major, sys.version_info.minor),
) -> Path:
    """Write the hook into its own directory under ``instrumented_dir`` and return that directory.

    ``implementation`` and ``version`` name the interpreter the hook serves; see ``get_spawn_hook_script``.
    """
    hook_dir = instrumented_dir / SPAWN_HOOK_DIRNAME
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / 'sitecustomize.py').write_text(get_spawn_hook_script(implementation, version), encoding='utf-8')
    return hook_dir


def export_spawn_hook(env: MutableMapping[str, str]) -> None:
    """Put the hook first on ``env['PYTHONPATH']`` when ``env`` names a sources file; otherwise do nothing.

    The hook directory is the one ``write_spawn_hook`` made next to the sources file. Calling this twice on
    one environment prepends it once.
    """
    sources_file = env.get(SOURCES_FILE_ENV_VAR)
    if not sources_file:
        return
    hook_dir = str(Path(sources_file).parent / SPAWN_HOOK_DIRNAME)
    existing = env.get('PYTHONPATH')
    inherited = [entry for entry in existing.split(os.pathsep) if entry != hook_dir] if existing else []
    env['PYTHONPATH'] = os.pathsep.join([hook_dir, *inherited])
