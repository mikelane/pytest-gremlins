"""The gremlin finder serves instrumented source for whatever file the import system resolves to (#597).

It never decides what a module is called. It asks the rest of ``sys.meta_path`` what would be loaded and
swaps the loader only when that answer is an instrumented file.
"""

from __future__ import annotations

import ast
import base64
from collections.abc import (
    Callable,
)
import importlib
import importlib.resources
import importlib.util
import inspect
import json
from pathlib import Path
import pickle
import pkgutil
import sys
import threading
import traceback
from types import (
    ModuleType,
    SimpleNamespace,
)

import pytest

from pytest_gremlins.instrumentation import origin_finder
from pytest_gremlins.instrumentation.origin_finder import (
    GremlinFinder,
    GremlinLoader,
    InstrumentedSources,
    file_identity,
    install,
    normalize_origin,
)
from pytest_gremlins.plugin import (
    _get_bootstrap_script,
    _get_lightweight_runner_script,
    _write_instrumented_sources,
)

Sources = InstrumentedSources
Install = Callable[[Sources], GremlinFinder]

INSTRUMENTED = 'VALUE = "instrumented"\n'
ORIGINAL = 'VALUE = "original"\n'


def _encode(source: str, filename: str | None = None) -> str:  # noqa: ARG001
    """Ship ``source`` the way sources.json does: as a parsed tree, pickled and base64 encoded."""
    return base64.b64encode(pickle.dumps(ast.parse(source))).decode('ascii')


def _entry(origin: Path, source: str = INSTRUMENTED) -> Sources:
    return {normalize_origin(str(origin)): {'tree': _encode(source, str(origin)), 'origin': str(origin)}}


def _entry_with_identity(origin: Path, source: str = INSTRUMENTED) -> Sources:
    entry = {'tree': _encode(source, str(origin)), 'origin': str(origin), 'identity': file_identity(str(origin))}
    return {normalize_origin(str(origin)): entry}


@pytest.fixture
def install_finder(monkeypatch: pytest.MonkeyPatch) -> Install:
    """Install the finder at the front of ``sys.meta_path``; restore the import state afterwards."""
    monkeypatch.setattr(sys, 'meta_path', list(sys.meta_path))
    monkeypatch.setattr(sys, 'modules', dict(sys.modules))
    return install


def _import(name: str) -> ModuleType:
    importlib.invalidate_caches()
    return importlib.import_module(name)


def _hardlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.hardlink_to(target)
    except OSError:
        pytest.skip('this platform cannot create hard links')


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('this platform cannot create symlinks')


@pytest.mark.medium
class DescribeGremlinFinderServesByOrigin:
    """A module is instrumented when the file the import system finds for it is an instrumented one."""

    def it_serves_instrumented_source_for_a_module_found_on_sys_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('plain_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(tmp_path / 'plain_mod.py'))

        assert _import('plain_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_leaves_a_module_that_is_not_instrumented_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('untouched_mod.py').write_text(ORIGINAL)
        tmp_path.joinpath('other_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(tmp_path / 'other_mod.py'))

        assert _import('untouched_mod').VALUE == 'original'  # type: ignore[attr-defined]

    def it_gives_the_module_the_real_file_as_its_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        origin = tmp_path / 'located_mod.py'
        origin.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(origin))

        module = _import('located_mod')

        assert (module.__file__, module.__spec__.origin) == (str(origin), str(origin))  # type: ignore[union-attr]

    def it_serves_a_package_init_as_a_package_whose_other_modules_still_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        package = tmp_path / 'served_pkg'
        package.mkdir()
        package.joinpath('__init__.py').write_text(ORIGINAL)
        package.joinpath('child.py').write_text('CHILD = 1\n')
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(package / '__init__.py'))

        module = _import('served_pkg')
        child = _import('served_pkg.child')

        assert (module.VALUE, list(module.__path__), child.CHILD) == (  # type: ignore[attr-defined]
            'instrumented',
            [str(package)],
            1,
        )

    def it_names_the_module_after_the_import_so_a_file_served_under_two_names_is_instrumented_in_both(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        outer = tmp_path / 'outer_pkg'
        outer.mkdir()
        outer.joinpath('__init__.py').write_text('')
        outer.joinpath('shared_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.syspath_prepend(str(outer))
        install_finder(_entry(outer / 'shared_mod.py'))

        under_package = _import('outer_pkg.shared_mod')
        under_root = _import('shared_mod')

        assert (under_package.VALUE, under_root.VALUE) == ('instrumented', 'instrumented')  # type: ignore[attr-defined]
        assert under_package is not under_root

    def it_serves_a_module_reached_through_a_symlinked_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        real = tmp_path / 'real'
        real.mkdir()
        real.joinpath('linked_mod.py').write_text(ORIGINAL)
        link = tmp_path / 'link'
        link.symlink_to(real, target_is_directory=True)
        monkeypatch.syspath_prepend(str(link))
        install_finder(_entry(real / 'linked_mod.py'))

        assert _import('linked_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_serves_a_module_inside_a_namespace_package(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        namespace = tmp_path / 'ns_pkg'
        namespace.mkdir()
        namespace.joinpath('leaf.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(namespace / 'leaf.py'))

        assert _import('ns_pkg.leaf').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_keeps_package_data_readable_through_importlib_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        package = tmp_path / 'data_pkg'
        package.mkdir()
        package.joinpath('__init__.py').write_text(ORIGINAL)
        package.joinpath('payload.txt').write_text('payload')
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(package / '__init__.py'))

        _import('data_pkg')

        assert importlib.resources.files('data_pkg').joinpath('payload.txt').read_text() == 'payload'

    def it_keeps_package_data_readable_through_pkgutil(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        package = tmp_path / 'blob_pkg'
        package.mkdir()
        package.joinpath('__init__.py').write_text(ORIGINAL)
        package.joinpath('blob.bin').write_bytes(b'blob')
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(package / '__init__.py'))

        _import('blob_pkg')

        assert pkgutil.get_data('blob_pkg', 'blob.bin') == b'blob'


class _ServesFromElsewhere:
    """A meta path finder, like an editable install's, that serves a module from a directory off ``sys.path``."""

    def __init__(self, name: str, origin: Path) -> None:
        self._name = name
        self._origin = origin

    def find_spec(self, fullname: str, _path: object = None, _target: object = None) -> object:
        if fullname != self._name:
            return None
        return importlib.util.spec_from_file_location(fullname, self._origin)


class _RaisesForName:
    def __init__(self, name: str) -> None:
        self._name = name

    def find_spec(self, fullname: str, _path: object = None, _target: object = None) -> object:
        if fullname == self._name:
            raise RuntimeError('finder blew up')
        return None


class _AsksTheImportSystemAgain:
    """A finder that resolves its own answer through ``importlib.util.find_spec``, re-entering ``sys.meta_path``."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._inside = False

    def find_spec(self, fullname: str, _path: object = None, _target: object = None) -> object:
        if fullname != self._name or self._inside:
            return None
        self._inside = True
        try:
            return importlib.util.find_spec(fullname)
        finally:
            self._inside = False


class _CountsLookups:
    """A meta path finder that records how often the import system asks it about a name."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.lookups = 0

    def find_spec(self, fullname: str, _path: object = None, _target: object = None) -> object:
        if fullname == self._name:
            self.lookups += 1
        return None


class _BlocksFirstLookup:
    """Holds the first lookup of a name inside ``find_spec`` until released, answering later ones at once."""

    def __init__(self, name: str, origin: Path) -> None:
        self._name = name
        self._origin = origin
        self._first = True
        self.entered = threading.Event()
        self.release = threading.Event()

    def find_spec(self, fullname: str, _path: object = None, _target: object = None) -> object:
        if fullname != self._name:
            return None
        spec = importlib.util.spec_from_file_location(fullname, self._origin)
        if self._first:
            self._first = False
            self.entered.set()
            self.release.wait(timeout=10)
        return spec


@pytest.mark.medium
class DescribeGremlinFinderDelegation:
    """Other meta path finders decide what is loaded; the gremlin finder only swaps the loader."""

    def it_instruments_a_module_served_by_another_meta_path_finder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        origin = tmp_path / 'elsewhere' / 'editable_mod.py'
        origin.parent.mkdir()
        origin.write_text(ORIGINAL)
        monkeypatch.setattr(sys, 'meta_path', [*sys.meta_path, _ServesFromElsewhere('editable_mod', origin)])
        install_finder(_entry(origin))

        assert _import('editable_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_lets_a_raising_finder_raise_for_the_import_system_instead_of_serving_past_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('guarded_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(sys, 'meta_path', [_RaisesForName('guarded_mod'), *sys.meta_path])
        install_finder(_entry(tmp_path / 'guarded_mod.py'))

        with pytest.raises(RuntimeError, match='finder blew up'):
            _import('guarded_mod')

    def it_does_not_recurse_when_a_finder_asks_the_import_system_for_the_same_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('again_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(sys, 'meta_path', [_AsksTheImportSystemAgain('again_mod'), *sys.meta_path])
        install_finder(_entry(tmp_path / 'again_mod.py'))

        assert _import('again_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_asks_the_later_finders_once_for_a_module_it_does_not_instrument(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('counted_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        counter = _CountsLookups('counted_mod')
        monkeypatch.setattr(sys, 'meta_path', [counter, *sys.meta_path])
        install_finder({})

        _import('counted_mod')

        assert counter.lookups == 1

    def it_serves_the_module_when_the_first_gremlin_finder_is_the_one_that_instruments_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('outer_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder({})
        install_finder(_entry(tmp_path / 'outer_mod.py'))

        assert _import('outer_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_serves_the_module_when_the_second_gremlin_finder_is_the_one_that_instruments_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('inner_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(tmp_path / 'inner_mod.py'))
        install_finder({})

        assert _import('inner_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_serves_a_module_to_one_thread_while_another_thread_is_resolving_the_same_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        origin = tmp_path / 'raced_mod.py'
        origin.write_text(ORIGINAL)
        blocker = _BlocksFirstLookup('raced_mod', origin)
        monkeypatch.setattr(sys, 'meta_path', [*sys.meta_path, blocker])
        finder = install_finder(_entry(origin))
        first_thread = threading.Thread(target=finder.find_spec, args=('raced_mod',))
        first_thread.start()
        assert blocker.entered.wait(timeout=10)

        try:
            spec = finder.find_spec('raced_mod')
        finally:
            blocker.release.set()
            first_thread.join(timeout=10)

        assert spec is not None
        assert isinstance(spec.loader, GremlinLoader)


@pytest.mark.medium
class DescribeGremlinFinderMetaPathEdges:
    """The finder walks whatever ``sys.meta_path`` holds without tripping over unusual entries."""

    def it_puts_the_finder_it_installs_ahead_of_every_other_finder(self, install_finder: Install) -> None:
        finder = install_finder({})

        assert sys.meta_path[0] is finder

    def it_answers_none_for_a_name_no_later_finder_can_resolve(self, install_finder: Install) -> None:
        finder = install_finder({})

        assert finder.find_spec('no_module_is_named_this_597') is None

    def it_skips_a_meta_path_entry_that_has_no_find_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('legacy_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(sys, 'meta_path', [object(), *sys.meta_path])
        install_finder(_entry(tmp_path / 'legacy_mod.py'))

        assert _import('legacy_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_does_not_ask_itself_when_it_sits_on_sys_meta_path_twice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('twice_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        finder = install_finder(_entry(tmp_path / 'twice_mod.py'))
        sys.meta_path.insert(1, finder)

        assert _import('twice_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_resolves_through_every_finder_when_it_was_never_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / 'detached_mod.py'
        origin.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        spec = GremlinFinder(_entry(origin)).find_spec('detached_mod')

        assert spec is not None
        assert isinstance(spec.loader, GremlinLoader)

    def it_leaves_a_spec_alone_when_its_file_is_not_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        ghost = tmp_path / 'ghost_mod.py'
        monkeypatch.setattr(sys, 'meta_path', [*sys.meta_path, _ServesFromElsewhere('ghost_mod', ghost)])
        tmp_path.joinpath('real_mod.py').write_text(ORIGINAL)
        finder = install_finder(_entry_with_identity(tmp_path / 'real_mod.py'))

        spec = finder.find_spec('ghost_mod')

        assert spec is not None
        assert spec.origin == str(ghost)
        assert not isinstance(spec.loader, GremlinLoader)


@pytest.mark.small
class DescribeGremlinLoaderResourceReader:
    """Package data is read through the loader that found the file, when there is one."""

    def it_has_no_resource_reader_when_the_original_loader_offers_none(self) -> None:
        loader = GremlinLoader(_encode(INSTRUMENTED, 'bare_mod.py'), original_loader=None)

        assert loader.get_resource_reader('bare_mod') is None

    def it_asks_the_original_loader_for_the_resource_reader(self) -> None:
        original = SimpleNamespace(get_resource_reader=lambda fullname: f'reader-for:{fullname}')
        loader = GremlinLoader(_encode(INSTRUMENTED, 'data_mod.py'), original_loader=original)

        assert loader.get_resource_reader('data_mod') == 'reader-for:data_mod'


def _module_from(name: str, origin: str) -> ModuleType:
    module = ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None, origin=origin)
    return module


@pytest.mark.small
class DescribeGremlinLoaderCompilesShippedTree:
    """The loader compiles the tree it was shipped under the spec's origin, so filename and lines survive (#563)."""

    def it_compiles_under_the_origin_of_the_module_spec(self) -> None:
        origin = 'C:\\project\\src\\origin_mod.py'
        module = _module_from('origin_mod', origin)

        GremlinLoader(_encode('def f():\n    return 1\n')).exec_module(module)

        assert module.f.__code__.co_filename == origin  # type: ignore[attr-defined]

    def it_keeps_the_line_numbers_of_the_shipped_tree(self) -> None:
        module = _module_from('lines_mod', 'lines_mod.py')

        GremlinLoader(_encode('\n' * 9 + 'def f():\n    return 1\n')).exec_module(module)

        assert module.f.__code__.co_firstlineno == 10  # type: ignore[attr-defined]

    def it_does_not_inherit_future_flags_from_the_loader_module(self) -> None:
        module = _module_from('flags_mod', 'flags_mod.py')

        GremlinLoader(_encode('def f():\n    return 1\n')).exec_module(module)

        assert module.f.__code__.co_flags & importlib.import_module('__future__').annotations.compiler_flag == 0  # type: ignore[attr-defined]


@pytest.mark.medium
class DescribeInstrumentedTracebacks:
    """A traceback from instrumented code names the real file and the line the failing statement is on (#563)."""

    def it_reports_the_original_line_number_of_a_failing_statement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        original = '# padding\n' * 20 + 'def boom():\n    value = 1\n    raise ValueError(value)\n'
        target = tmp_path / 'traceback_mod.py'
        target.write_text(original)
        monkeypatch.syspath_prepend(str(tmp_path))
        sources_dir = _write_instrumented_sources({str(target): ast.parse(original)}, tmp_path)
        install_finder(json.loads((sources_dir / 'sources.json').read_text()))
        module = _import('traceback_mod')

        with pytest.raises(ValueError, match='1') as raised:
            module.boom()  # type: ignore[attr-defined]

        frame = traceback.extract_tb(raised.value.__traceback__)[-1]
        assert (frame.filename, frame.lineno, frame.line) == (str(target), 23, 'raise ValueError(value)')


@pytest.mark.medium
class DescribeGremlinFinderCompileFilename:
    """The finder hands the loader the origin of the spec it resolved (#563)."""

    def it_hands_the_origin_of_the_resolved_spec_to_the_loader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'filename_mod.py'
        target.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(target, 'def f():\n    return 1\n'))

        module = _import('filename_mod')

        assert module.f.__code__.co_filename == str(target)


@pytest.mark.medium
class DescribeGremlinFinderServesByFileIdentity:
    """A path spelling that misses the string key still reaches the instrumented file by what it is on disk."""

    def it_serves_a_file_whose_spelling_differs_but_whose_inode_is_an_instrumented_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'real' / 'twin_mod.py'
        target.parent.mkdir()
        target.write_text(ORIGINAL)
        spelling = tmp_path / 'elsewhere' / 'twin_mod.py'
        spelling.parent.mkdir()
        _hardlink_or_skip(spelling, target)
        monkeypatch.syspath_prepend(str(spelling.parent))
        install_finder(_entry_with_identity(target))

        assert _import('twin_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_leaves_a_different_file_with_the_same_name_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'real' / 'namesake_mod.py'
        target.parent.mkdir()
        target.write_text(ORIGINAL)
        namesake = tmp_path / 'elsewhere' / 'namesake_mod.py'
        namesake.parent.mkdir()
        namesake.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(namesake.parent))
        install_finder(_entry_with_identity(target))

        assert _import('namesake_mod').VALUE == 'original'  # type: ignore[attr-defined]

    def it_never_matches_on_an_entry_without_an_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'real' / 'anon_mod.py'
        target.parent.mkdir()
        target.write_text(ORIGINAL)
        spelling = tmp_path / 'elsewhere' / 'anon_mod.py'
        spelling.parent.mkdir()
        _hardlink_or_skip(spelling, target)
        monkeypatch.syspath_prepend(str(spelling.parent))
        install_finder(_entry(target))

        assert _import('anon_mod').VALUE == 'original'  # type: ignore[attr-defined]


@pytest.mark.medium
class DescribeFileIdentity:
    """A file's identity is its device and inode."""

    def it_is_the_same_for_two_names_of_one_file(self, tmp_path: Path) -> None:
        target = tmp_path / 'a.py'
        target.write_text('')
        alias = tmp_path / 'b.py'
        _hardlink_or_skip(alias, target)

        assert file_identity(str(alias)) == file_identity(str(target))

    def it_differs_between_two_files(self, tmp_path: Path) -> None:
        tmp_path.joinpath('a.py').write_text('')
        tmp_path.joinpath('b.py').write_text('')

        assert file_identity(str(tmp_path / 'a.py')) != file_identity(str(tmp_path / 'b.py'))

    def it_is_none_for_a_file_that_does_not_exist(self, tmp_path: Path) -> None:
        assert file_identity(str(tmp_path / 'missing.py')) is None


@pytest.mark.small
class DescribeFileIdentityOfZeroInode:
    """ReFS and network drives report an inode of 0 or reuse inodes, so a zero inode is no identity."""

    def it_is_none_when_the_filesystem_reports_an_inode_of_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(origin_finder.os, 'stat', lambda _path: SimpleNamespace(st_dev=7, st_ino=0))

        assert file_identity('anything.py') is None


@pytest.mark.medium
class DescribeGremlinFinderBasenamePrefilter:
    """Only a file named like an instrumented one is worth resolving to its real path."""

    def it_does_not_resolve_the_real_path_of_a_module_no_target_is_named_like(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        tmp_path.joinpath('target_mod.py').write_text(ORIGINAL)
        tmp_path.joinpath('bystander_mod.py').write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(tmp_path / 'target_mod.py'))
        resolved: list[str] = []
        original_normalize_origin = origin_finder.normalize_origin
        monkeypatch.setattr(
            origin_finder, 'normalize_origin', lambda path: resolved.append(path) or original_normalize_origin(path)
        )

        _import('bystander_mod')

        assert resolved == []

    def it_still_leaves_a_module_alone_when_it_only_shares_a_target_s_file_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'real' / 'shared_name_mod.py'
        target.parent.mkdir()
        target.write_text(ORIGINAL)
        namesake = tmp_path / 'elsewhere' / 'shared_name_mod.py'
        namesake.parent.mkdir()
        namesake.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(namesake.parent))
        install_finder(_entry(target))

        assert _import('shared_name_mod').VALUE == 'original'  # type: ignore[attr-defined]

    def it_matches_file_names_without_regard_to_case(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        origin = tmp_path / 'MixedCaseMod.py'
        origin.write_text(ORIGINAL)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry(origin))

        assert _import('MixedCaseMod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_serves_a_file_under_the_name_listed_for_it_even_when_its_origin_is_named_differently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'core_impl.py'
        target.write_text(ORIGINAL)
        alias = tmp_path / 'listed_alias_mod.py'
        _symlink_or_skip(alias, target)
        monkeypatch.syspath_prepend(str(tmp_path))
        sources = _entry(target)
        sources[normalize_origin(str(target))]['file_names'] = ['core_impl.py', 'listed_alias_mod.py']
        install_finder(sources)

        assert _import('listed_alias_mod').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_reaches_a_differently_named_hard_link_to_a_target_through_file_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'real' / 'core_impl.py'
        target.parent.mkdir()
        target.write_text(ORIGINAL)
        alias = tmp_path / 'vendor' / 'thing.py'
        alias.parent.mkdir()
        _hardlink_or_skip(alias, target)
        monkeypatch.syspath_prepend(str(alias.parent))
        install_finder(_entry_with_identity(target))

        assert _import('thing').VALUE == 'instrumented'  # type: ignore[attr-defined]

    def it_calls_file_identity_when_basename_misses_to_reach_differently_named_symlinks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install_finder: Install
    ) -> None:
        target = tmp_path / 'core_impl.py'
        target.write_text(ORIGINAL)
        alias = tmp_path / 'differently_named.py'
        _symlink_or_skip(alias, target)
        monkeypatch.syspath_prepend(str(tmp_path))
        install_finder(_entry_with_identity(target))
        called: list[str] = []
        original_file_identity = origin_finder.file_identity
        monkeypatch.setattr(
            origin_finder, 'file_identity', lambda path: called.append(path) or original_file_identity(path)
        )

        _import('differently_named')

        assert called == [str(alias)]


@pytest.mark.small
class DescribeNormalizeOrigin:
    """Both sides of the sources file agree on one spelling of a path."""

    def it_is_the_same_for_a_relative_and_an_absolute_spelling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert normalize_origin('a/../mod.py') == normalize_origin(str(tmp_path / 'mod.py'))


@pytest.mark.small
class DescribeSharedFinderSource:
    """Both generated scripts carry the same finder, so they cannot drift apart."""

    @pytest.mark.parametrize('script', [_get_bootstrap_script, _get_lightweight_runner_script])
    def it_embeds_the_finder_module_verbatim(self, script: Callable[[], str]) -> None:
        assert inspect.getsource(origin_finder) in script()
