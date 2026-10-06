"""Module names follow the sys.path / ``pythonpath`` entry a file is imported through (#597)."""

from __future__ import annotations

import ast
import json
import logging
import os
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from pytest_gremlins.plugin import (
    _collect_import_roots,
    _get_import_roots,
    _path_to_module_name,
    _write_instrumented_sources,
)

_TREE = ast.parse('x = 1\n')


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('')
    return path


def _registered(tmp_path: Path, files: list[Path], import_roots: list[Path]) -> dict[str, dict[str, str]]:
    result_dir = _write_instrumented_sources({str(file): _TREE for file in files}, tmp_path, import_roots)
    registered: dict[str, dict[str, str]] = json.loads((result_dir / 'sources.json').read_text())
    return registered


@pytest.mark.medium
class DescribePathToModuleNameWithImportRoots:
    """The name is the file's path relative to the longest import root that contains it."""

    @pytest.mark.parametrize(
        ('relative_file', 'expected'),
        [
            ('a/util/core.py', 'util.core'),
            ('a/util/__init__.py', 'util'),
            ('a/lone.py', 'lone'),
        ],
    )
    def it_names_a_file_relative_to_its_pythonpath_entry(
        self, tmp_path: Path, relative_file: str, expected: str
    ) -> None:
        assert _path_to_module_name(tmp_path / relative_file, tmp_path, [tmp_path / 'a']) == expected

    @pytest.mark.parametrize('roots_in_order', [('', 'a'), ('a', '')])
    def it_prefers_the_longest_containing_root_whatever_the_order(
        self, tmp_path: Path, roots_in_order: tuple[str, str]
    ) -> None:
        roots = [tmp_path / name for name in roots_in_order]

        assert _path_to_module_name(tmp_path / 'a' / 'util' / 'core.py', tmp_path, roots) == 'util.core'

    def it_falls_back_to_the_rootdir_when_no_root_contains_the_file(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / 'elsewhere'

        assert _path_to_module_name(tmp_path / 'pkg' / 'mod.py', tmp_path, [elsewhere]) == 'pkg.mod'

    def it_falls_back_to_stripping_src_when_no_root_contains_the_file(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / 'elsewhere'

        assert _path_to_module_name(tmp_path / 'src' / 'pkg' / 'mod.py', tmp_path, [elsewhere]) == 'pkg.mod'

    def it_resolves_a_symlinked_root(self, tmp_path: Path) -> None:
        real = tmp_path / 'real'
        _touch(real / 'util' / 'core.py')
        link = tmp_path / 'link'
        link.symlink_to(real, target_is_directory=True)

        assert _path_to_module_name(real / 'util' / 'core.py', tmp_path, [link]) == 'util.core'

    def it_resolves_a_file_reached_through_a_symlinked_directory(self, tmp_path: Path) -> None:
        real = tmp_path / 'real'
        _touch(real / 'util' / 'core.py')
        link = tmp_path / 'link'
        link.symlink_to(real, target_is_directory=True)

        assert _path_to_module_name(link / 'util' / 'core.py', tmp_path, [real]) == 'util.core'

    def it_keeps_the_name_of_a_symlinked_file(self, tmp_path: Path) -> None:
        real = _touch(tmp_path / 'store' / 'impl.py')
        entry = tmp_path / 'a'
        entry.mkdir()
        (entry / 'alias.py').symlink_to(real)

        assert _path_to_module_name(entry / 'alias.py', tmp_path, [entry]) == 'alias'

    @pytest.mark.skipif(os.name != 'nt', reason='Windows paths compare case-insensitively')
    def it_matches_a_root_whose_case_differs_on_windows(self, tmp_path: Path) -> None:
        shouting = Path(str(tmp_path / 'A').upper())

        assert _path_to_module_name(tmp_path / 'a' / 'util.py', tmp_path, [shouting]) == 'util'


@pytest.mark.medium
class DescribeCollectImportRoots:
    """Import roots are the ini ``pythonpath`` entries, then sys.path, then the rootdir fallbacks."""

    def it_lists_pythonpath_entries_before_sys_path_and_the_rootdir_fallbacks(self, tmp_path: Path) -> None:
        roots = _collect_import_roots([tmp_path / 'a'], [str(tmp_path / 'b')], tmp_path)

        assert roots == [(tmp_path / 'a').resolve(), (tmp_path / 'b').resolve(), tmp_path / 'src', tmp_path]

    def it_resolves_a_relative_pythonpath_entry_against_the_rootdir(self, tmp_path: Path) -> None:
        roots = _collect_import_roots([Path('a')], [], tmp_path)

        assert roots[0] == (tmp_path / 'a').resolve()

    def it_keeps_the_first_occurrence_of_a_repeated_entry(self, tmp_path: Path) -> None:
        roots = _collect_import_roots([tmp_path / 'a'], [str(tmp_path / 'b'), str(tmp_path / 'a')], tmp_path)

        assert roots.count((tmp_path / 'a').resolve()) == 1
        assert roots.index((tmp_path / 'a').resolve()) < roots.index((tmp_path / 'b').resolve())

    def it_skips_the_empty_sys_path_entry(self, tmp_path: Path) -> None:
        assert _collect_import_roots([], [''], tmp_path) == [tmp_path / 'src', tmp_path]


@pytest.mark.medium
class DescribeGetImportRootsIgnoresTheParentsWorkingDirectoryEntry:
    """``python -m pytest`` puts the cwd on sys.path; the bootstrap subprocess does not have it."""

    @staticmethod
    def _config() -> pytest.Config:
        config = create_autospec(pytest.Config, instance=True)
        config.getini.return_value = []
        return config

    def it_does_not_name_a_package_relative_to_a_cwd_inside_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_dir = tmp_path / 'src' / 'pkg'
        package_dir.mkdir(parents=True)
        monkeypatch.chdir(package_dir)
        monkeypatch.setattr('sys.path', [str(package_dir)])
        monkeypatch.delenv('PYTHONPATH', raising=False)

        roots = _get_import_roots(self._config(), tmp_path)

        assert _path_to_module_name(package_dir / 'core.py', tmp_path, roots) == 'pkg.core'

    def it_keeps_a_cwd_entry_the_subprocess_also_gets_from_pythonpath(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_dir = tmp_path / 'src' / 'pkg'
        package_dir.mkdir(parents=True)
        monkeypatch.chdir(package_dir)
        monkeypatch.setattr('sys.path', [str(package_dir)])
        monkeypatch.setenv('PYTHONPATH', str(package_dir))

        roots = _get_import_roots(self._config(), tmp_path)

        assert _path_to_module_name(package_dir / 'core.py', tmp_path, roots) == 'core'


@pytest.mark.medium
class DescribeCollisionsFollowImportPrecedence:
    """Two files that map to one name are resolved the way Python would: the earlier root wins."""

    @pytest.mark.parametrize('src_first', [True, False])
    def it_serves_the_module_on_the_earlier_root_whatever_the_target_order(
        self, tmp_path: Path, src_first: bool
    ) -> None:
        top = _touch(tmp_path / 'a.py')
        under_src = _touch(tmp_path / 'src' / 'a.py')
        files = [under_src, top] if src_first else [top, under_src]

        registered = _registered(tmp_path, files, [tmp_path / 'src', tmp_path])

        assert registered['a']['origin'] == str(under_src)

    def it_serves_a_module_on_an_earlier_root_over_a_package_on_a_later_one(self, tmp_path: Path) -> None:
        module = _touch(tmp_path / 'first' / 'name.py')
        package_init = _touch(tmp_path / 'second' / 'name' / '__init__.py')

        registered = _registered(tmp_path, [package_init, module], [tmp_path / 'first', tmp_path / 'second'])

        assert registered['name']['origin'] == str(module)

    def it_serves_a_package_over_a_module_on_the_same_root(self, tmp_path: Path) -> None:
        module = _touch(tmp_path / 'a' / 'name.py')
        package_init = _touch(tmp_path / 'a' / 'name' / '__init__.py')

        registered = _registered(tmp_path, [module, package_init], [tmp_path / 'a'])

        assert registered['name']['origin'] == str(package_init)

    def it_names_the_winning_module_not_a_package_in_the_shadow_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        top = _touch(tmp_path / 'a.py')
        under_src = _touch(tmp_path / 'src' / 'a.py')

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.plugin'):
            _registered(tmp_path, [top, under_src], [tmp_path / 'src', tmp_path])

        assert [record.getMessage().split(' is shadowed')[0] for record in caplog.records] == [
            f"Module name 'a' is taken by the module {under_src}; {top}"
        ]

    def it_names_the_winning_package_in_the_shadow_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        module = _touch(tmp_path / 'pkg.py')
        package_init = _touch(tmp_path / 'pkg' / '__init__.py')

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.plugin'):
            _registered(tmp_path, [module, package_init], [tmp_path])

        assert [record.getMessage().split(' is shadowed')[0] for record in caplog.records] == [
            f"Module name 'pkg' is taken by the package {package_init}; {module}"
        ]
