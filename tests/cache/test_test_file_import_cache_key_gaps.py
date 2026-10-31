"""Edits the import walk must see: pytest_plugins, ini pythonpath, BOM and coding-declared sources (#910)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins import plugin

TEST_FILE = 'tests/test_a.py'
FIXTURE_MODULE = b'import pytest\n\n\n@pytest.fixture\ndef value():\n    return {value}\n'


def _test_hash(
    rootdir: Path,
    python_files: tuple[str, ...] = plugin.DEFAULT_TEST_FILE_PATTERNS,
    pythonpath: tuple[Path, ...] = (),
) -> str:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    session.test_node_ids = {f'{TEST_FILE}::test_x': f'{TEST_FILE}::test_x'}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir, python_files, pythonpath)
    return session.test_hashes[TEST_FILE]


def _write(root: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _fixture_module(value: int) -> bytes:
    return FIXTURE_MODULE.replace(b'{value}', str(value).encode())


@pytest.mark.medium
class DescribePytestPluginsModulesFoldedIntoTestHash:
    @pytest.mark.parametrize(
        'declaration',
        [
            pytest.param("pytest_plugins = ['tests.test_utils']", id='list'),
            pytest.param("pytest_plugins = ('tests.test_utils',)", id='tuple'),
            pytest.param("pytest_plugins = 'tests.test_utils'", id='string'),
            pytest.param("pytest_plugins: list[str] = ['tests.test_utils']", id='annotated'),
        ],
    )
    def it_misses_the_cache_after_editing_a_test_named_module_a_conftest_declares(
        self, tmp_path: Path, declaration: str
    ) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/conftest.py': f'{declaration}\n'.encode(),
                'tests/test_utils.py': _fixture_module(1),
                'tests/test_a.py': b'def test_x(value): assert value == 1\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_utils.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path) != before

    def it_misses_the_cache_after_editing_a_test_named_module_the_test_file_declares(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/test_utils.py': _fixture_module(1),
                'tests/test_a.py': b"pytest_plugins = ['tests.test_utils']\ndef test_x(value): assert value == 1\n",
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_utils.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path) != before

    def it_misses_the_cache_after_editing_a_plugin_module_when_python_files_matches_every_file(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/conftest.py': b"pytest_plugins = ['tests.fixtures']\n",
                'tests/fixtures.py': _fixture_module(1),
                'tests/test_a.py': b'def test_x(value): assert value == 1\n',
            },
        )
        before = _test_hash(tmp_path, ('*.py',))

        (tmp_path / 'tests/fixtures.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path, ('*.py',)) != before

    def it_ignores_a_pytest_plugins_assignment_that_is_not_at_module_level(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/conftest.py': b"def configure():\n    pytest_plugins = ['tests.test_utils']\n",
                'tests/test_utils.py': _fixture_module(1),
                'tests/test_a.py': b'def test_x(): pass\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_utils.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path) == before


@pytest.mark.medium
class DescribeIniPythonpathEntriesSearchedForImports:
    def it_misses_the_cache_after_editing_a_test_named_module_found_through_a_pythonpath_entry(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            {
                'tests/support/test_shared.py': b'def make(): return 1\n',
                'tests/test_a.py': b'from test_shared import make\n',
            },
        )
        pythonpath = (tmp_path / 'tests' / 'support',)
        before = _test_hash(tmp_path, pythonpath=pythonpath)

        (tmp_path / 'tests/support/test_shared.py').write_bytes(b'def make(): return 2\n')

        assert _test_hash(tmp_path, pythonpath=pythonpath) != before

    def it_keeps_the_key_when_the_module_is_off_the_pythonpath(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/support/test_shared.py': b'def make(): return 1\n',
                'tests/test_a.py': b'from test_shared import make\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/support/test_shared.py').write_bytes(b'def make(): return 2\n')

        assert _test_hash(tmp_path) == before


@pytest.mark.medium
class DescribeSourceEncodingsReadByTheImportWalk:
    def it_follows_imports_in_a_bom_prefixed_test_file(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/test_a.py': b'\xef\xbb\xbffrom tests.test_b import make\n',
                'tests/test_b.py': b'def make(): return 1\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_b.py').write_bytes(b'def make(): return 2\n')

        assert _test_hash(tmp_path) != before

    def it_follows_imports_in_a_test_file_with_a_coding_declaration(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/test_a.py': b'# -*- coding: latin-1 -*-\nNAME = "caf\xe9"\nfrom tests.test_b import make\n',
                'tests/test_b.py': b'def make(): return 1\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_b.py').write_bytes(b'def make(): return 2\n')

        assert _test_hash(tmp_path) != before


@pytest.mark.medium
class DescribeImportNamesThatMatchUnreadablePaths:
    def it_computes_a_key_when_probing_an_import_name_raises_a_permission_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, {'tests/test_a.py': b'import redis\n'})
        real_is_file = Path.is_file

        def is_file(self: Path) -> bool:
            if 'redis' in self.parts:
                raise PermissionError(13, 'Permission denied', str(self))
            return real_is_file(self)

        monkeypatch.setattr(Path, 'is_file', is_file)

        assert len(_test_hash(tmp_path)) == 64


@pytest.mark.medium
class DescribePytestPluginsInsideModuleLevelBlocks:
    @pytest.mark.parametrize(
        'conftest',
        [
            pytest.param(
                b'try:\n    import xdist\nexcept ImportError:\n    pass\n'
                b"else:\n    pytest_plugins = ['tests.test_utils']\n",
                id='try-else',
            ),
            pytest.param(b"try:\n    pytest_plugins = ['tests.test_utils']\nfinally:\n    pass\n", id='try-body'),
            pytest.param(
                b"try:\n    pass\nexcept ImportError:\n    pytest_plugins = ['tests.test_utils']\n", id='except'
            ),
            pytest.param(
                b"import sys\nif sys.platform == 'none':\n    pass\nelse:\n    pytest_plugins = ['tests.test_utils']\n",
                id='if-else',
            ),
        ],
    )
    def it_misses_the_cache_after_editing_a_test_named_plugin_declared_in_the_block(
        self, tmp_path: Path, conftest: bytes
    ) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/conftest.py': conftest,
                'tests/test_utils.py': _fixture_module(1),
                'tests/test_a.py': b'def test_x(value): assert value == 1\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_utils.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path) != before

    def it_ignores_a_plugin_declared_inside_a_function_nested_in_a_module_level_block(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                'tests/__init__.py': b'',
                'tests/conftest.py': b"if True:\n    def configure():\n        pytest_plugins = ['tests.test_utils']\n",
                'tests/test_utils.py': _fixture_module(1),
                'tests/test_a.py': b'def test_x(): pass\n',
            },
        )
        before = _test_hash(tmp_path)

        (tmp_path / 'tests/test_utils.py').write_bytes(_fixture_module(2))

        assert _test_hash(tmp_path) == before
