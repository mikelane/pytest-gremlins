"""Tests for the ``sitecustomize`` hook that gives a ``multiprocessing`` spawn child the gremlin finder (#604)."""

from __future__ import annotations

import ast
import base64
from collections.abc import Callable
import inspect
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys

import pytest

from pytest_gremlins.instrumentation import origin_finder
from pytest_gremlins.instrumentation.origin_finder import (
    install,
    normalize_origin,
)
from pytest_gremlins.instrumentation.spawn_hook import (
    SOURCES_FILE_ENV_VAR,
    SPAWN_HOOK_DIRNAME,
    export_spawn_hook,
    get_spawn_hook_script,
    write_spawn_hook,
)

INSTRUMENTED = 'VALUE = "instrumented"\n'
ORIGINAL = 'VALUE = "original"\n'
CHILD_TIMEOUT_SECONDS = 60

RunChild = Callable[..., subprocess.CompletedProcess[str]]


def _sources_for(origin: Path, source: str = INSTRUMENTED) -> dict[str, dict[str, object]]:
    tree = base64.b64encode(pickle.dumps(ast.parse(source))).decode('ascii')
    return {normalize_origin(str(origin)): {'tree': tree, 'source': source, 'origin': str(origin)}}


def _finders_in(meta_path: list[object]) -> list[object]:
    return [finder for finder in meta_path if getattr(finder, 'is_gremlin_finder', False)]


@pytest.fixture
def isolated_meta_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore ``sys.meta_path`` and ``sys.modules`` after a test that installs a finder."""
    monkeypatch.setattr(sys, 'meta_path', list(sys.meta_path))
    monkeypatch.setattr(sys, 'modules', dict(sys.modules))


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A module whose original text differs from its instrumented text."""
    module = tmp_path / 'project' / 'spawn_target.py'
    module.parent.mkdir()
    module.write_text(ORIGINAL)
    return module


@pytest.fixture
def sources_file(tmp_path: Path, target: Path) -> Path:
    """A ``sources.json`` that serves the instrumented text of ``target``."""
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps(_sources_for(target)))
    return path


@pytest.fixture
def hook_dir(tmp_path: Path) -> Path:
    """The directory holding a freshly written spawn hook for this interpreter."""
    return write_spawn_hook(tmp_path)


@pytest.fixture
def run_child(target: Path) -> RunChild:
    """Run a fresh interpreter, as a ``multiprocessing`` spawn child is, with the given environment."""

    def run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
        environment = {name: value for name, value in os.environ.items() if name != 'PYTHONPATH'}
        hook_path = env.pop('hook_path', '')
        environment['PYTHONPATH'] = os.pathsep.join(filter(None, [hook_path, str(target.parent)]))
        environment.update(env)
        return subprocess.run(
            [sys.executable, '-c', code],
            env=environment,
            capture_output=True,
            encoding='utf-8',
            timeout=CHILD_TIMEOUT_SECONDS,
            check=False,
        )

    return run


@pytest.mark.medium
@pytest.mark.usefixtures('isolated_meta_path')
class DescribeInstallIsIdempotent:
    """The test process gets the finder from the hook and from the bootstrap, and must hold one."""

    def it_returns_the_installed_finder_when_asked_again(self, target: Path) -> None:
        sources = _sources_for(target)

        first = install(sources)
        second = install(dict(sources))

        assert (second is first, len(_finders_in(sys.meta_path))) == (True, 1)

    def it_puts_the_finder_back_in_front_of_a_hook_that_displaced_it(self, target: Path) -> None:
        sources = _sources_for(target)
        finder = install(sources)
        sys.meta_path.insert(0, object())  # type: ignore[arg-type]  # pytest's assertion-rewrite hook, say

        install(sources)

        assert sys.meta_path[0] is finder

    def it_replaces_the_finder_when_the_sources_differ(self, target: Path) -> None:
        first = install(_sources_for(target))
        second = install(_sources_for(target, 'VALUE = "other"\n'))

        assert (second is not first, _finders_in(sys.meta_path)) == (True, [second])

    def it_recognises_a_finder_installed_by_the_copy_of_the_finder_a_hook_embeds(
        self,
        sources_file: Path,
        hook_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(SOURCES_FILE_ENV_VAR, str(sources_file))
        hook_namespace: dict[str, object] = {
            '__name__': 'sitecustomize',
            '__file__': str(hook_dir / 'sitecustomize.py'),
        }
        exec(compile(get_spawn_hook_script(), 'sitecustomize.py', 'exec'), hook_namespace)  # noqa: S102
        embedded_copy = _finders_in(sys.meta_path)[0]

        assert (install(json.loads(sources_file.read_text())) is embedded_copy, len(_finders_in(sys.meta_path))) == (
            True,
            1,
        )


@pytest.mark.medium
class DescribeSpawnHookScript:
    """A fresh interpreter that finds the hook on ``PYTHONPATH`` serves instrumented sources."""

    def it_serves_instrumented_source_in_a_fresh_interpreter(
        self, run_child: RunChild, sources_file: Path, hook_dir: Path
    ) -> None:
        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=str(hook_dir),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip()) == (0, 'instrumented')

    def it_leaves_the_interpreter_alone_when_no_sources_file_is_named(
        self, run_child: RunChild, hook_dir: Path
    ) -> None:
        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=str(hook_dir),
        )

        assert (completed.returncode, completed.stdout.strip()) == (0, 'original')

    def it_runs_the_sitecustomize_the_hook_shadows(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path, hook_dir: Path
    ) -> None:
        users_site_dir = tmp_path / 'users_site'
        users_site_dir.mkdir()
        users_site_dir.joinpath('sitecustomize.py').write_text(
            'import os\nos.environ["USERS_SITECUSTOMIZE_RAN"] = "yes"\n'
        )

        completed = run_child(
            'import os, spawn_target; print(os.environ.get("USERS_SITECUSTOMIZE_RAN"), spawn_target.VALUE)',
            hook_path=os.pathsep.join([str(hook_dir), str(users_site_dir)]),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip()) == (0, 'yes instrumented')

    def it_chains_past_the_hook_of_an_enclosing_gremlin_run_to_the_users_sitecustomize(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path, hook_dir: Path
    ) -> None:
        enclosing_run = tmp_path / 'enclosing_run'
        enclosing_run.mkdir()
        enclosing_hook_dir = write_spawn_hook(enclosing_run)
        users_site_dir = tmp_path / 'users_site'
        users_site_dir.mkdir()
        users_site_dir.joinpath('sitecustomize.py').write_text(
            'import os\n'
            'os.environ["USERS_SITECUSTOMIZE_RUNS"] = str(int(os.environ.get("USERS_SITECUSTOMIZE_RUNS", "0")) + 1)\n'
        )

        completed = run_child(
            'import os, spawn_target; print(os.environ.get("USERS_SITECUSTOMIZE_RUNS"), spawn_target.VALUE)',
            hook_path=os.pathsep.join([str(hook_dir), str(enclosing_hook_dir), str(users_site_dir)]),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip(), completed.stderr) == (0, '1 instrumented', '')

    def it_reports_a_failing_sitecustomize_it_chains_and_still_installs_the_finder(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path, hook_dir: Path
    ) -> None:
        users_site_dir = tmp_path / 'users_site'
        users_site_dir.mkdir()
        users_site_dir.joinpath('sitecustomize.py').write_text('raise RuntimeError("users sitecustomize is broken")\n')

        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=os.pathsep.join([str(hook_dir), str(users_site_dir)]),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (
            completed.returncode,
            completed.stdout.strip(),
            'users sitecustomize is broken' in completed.stderr,
        ) == (
            0,
            'instrumented',
            True,
        )

    def it_keeps_itself_as_the_sitecustomize_module_when_the_one_it_chains_fails(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path, hook_dir: Path
    ) -> None:
        users_site_dir = tmp_path / 'users_site'
        users_site_dir.mkdir()
        users_site_dir.joinpath('sitecustomize.py').write_text('raise RuntimeError("users sitecustomize is broken")\n')

        completed = run_child(
            'import pathlib, sys; print(pathlib.Path(sys.modules["sitecustomize"].__file__).parent.name)',
            hook_path=os.pathsep.join([str(hook_dir), str(users_site_dir)]),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip()) == (0, SPAWN_HOOK_DIRNAME)

    def it_serves_the_original_source_to_an_interpreter_of_another_python_version(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path
    ) -> None:
        hook_dir = write_spawn_hook(tmp_path / 'other', implementation=sys.implementation.name, version=(2, 7))

        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=str(hook_dir),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip(), completed.stderr) == (0, 'original', '')

    def it_serves_the_original_source_to_an_interpreter_of_another_implementation(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path
    ) -> None:
        hook_dir = write_spawn_hook(tmp_path / 'other', implementation='notpython', version=sys.version_info[:2])

        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=str(hook_dir),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip(), completed.stderr) == (0, 'original', '')

    def it_still_runs_the_users_sitecustomize_in_an_interpreter_of_another_python_version(
        self, tmp_path: Path, run_child: RunChild, sources_file: Path
    ) -> None:
        hook_dir = write_spawn_hook(tmp_path / 'other', implementation=sys.implementation.name, version=(2, 7))
        users_site_dir = tmp_path / 'users_site'
        users_site_dir.mkdir()
        users_site_dir.joinpath('sitecustomize.py').write_text(
            'import os\nos.environ["USERS_SITECUSTOMIZE_RAN"] = "yes"\n'
        )

        completed = run_child(
            'import os, spawn_target; print(os.environ.get("USERS_SITECUSTOMIZE_RAN"), spawn_target.VALUE)',
            hook_path=os.pathsep.join([str(hook_dir), str(users_site_dir)]),
            **{SOURCES_FILE_ENV_VAR: str(sources_file)},
        )

        assert (completed.returncode, completed.stdout.strip()) == (0, 'yes original')

    def it_says_so_on_stderr_and_lets_the_interpreter_start_when_the_sources_cannot_be_read(
        self, tmp_path: Path, run_child: RunChild, hook_dir: Path
    ) -> None:
        missing_sources_file = tmp_path / 'no_such_sources.json'

        completed = run_child(
            'import spawn_target; print(spawn_target.VALUE)',
            hook_path=str(hook_dir),
            **{SOURCES_FILE_ENV_VAR: str(missing_sources_file)},
        )

        assert (
            completed.returncode,
            completed.stdout.strip(),
            f'pytest-gremlins: could not install the import finder in this interpreter ({missing_sources_file})'
            in completed.stderr,
            'FileNotFoundError' in completed.stderr,
        ) == (0, 'original', True, True)


@pytest.mark.small
class DescribeSpawnHookOnAnOldInterpreter:
    """The hook starts cleanly in an interpreter too old for the finder it carries (#604).

    The finder's source evaluates ``X | None`` and ``dict[...]`` at import, which Python 3.9 and earlier cannot. The
    hook therefore runs only the version gate and the chaining to the user's ``sitecustomize`` at module level, and
    compiles the finder after the gate has passed.
    """

    def it_parses_under_the_python_3_6_grammar(self) -> None:
        tree = ast.parse(get_spawn_hook_script(), feature_version=(3, 6))

        assert isinstance(tree, ast.Module)

    def it_defines_nothing_of_the_finder_at_module_level(self) -> None:
        tree = ast.parse(get_spawn_hook_script())

        definitions = {node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))}

        assert definitions & {'install', 'GremlinFinder'} == set()

    def it_does_not_run_the_finder_source_in_an_interpreter_of_another_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sources_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(inspect, 'getsource', lambda _module: 'raise RuntimeError("finder source ran")\n')
        monkeypatch.setenv(SOURCES_FILE_ENV_VAR, str(sources_file))
        monkeypatch.setattr(sys, 'path', [])
        monkeypatch.setattr(sys, 'modules', dict(sys.modules))
        script = get_spawn_hook_script(version=(2, 7))

        exec(compile(script, 'sitecustomize.py', 'exec'), {'__name__': 'sitecustomize', '__file__': str(tmp_path)})  # noqa: S102

        assert capsys.readouterr().err == ''

    def it_runs_the_finder_source_in_an_interpreter_of_the_same_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sources_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(inspect, 'getsource', lambda _module: 'raise RuntimeError("finder source ran")\n')
        monkeypatch.setenv(SOURCES_FILE_ENV_VAR, str(sources_file))
        monkeypatch.setattr(sys, 'path', [])
        monkeypatch.setattr(sys, 'modules', dict(sys.modules))
        script = get_spawn_hook_script()

        exec(compile(script, 'sitecustomize.py', 'exec'), {'__name__': 'sitecustomize', '__file__': str(tmp_path)})  # noqa: S102

        assert 'finder source ran' in capsys.readouterr().err


@pytest.mark.medium
class DescribeWriteSpawnHook:
    """The hook lives in a directory of its own, so only ``sitecustomize`` becomes importable."""

    def it_writes_sitecustomize_into_a_dedicated_subdirectory(self, tmp_path: Path) -> None:
        hook_dir = write_spawn_hook(tmp_path)

        assert (hook_dir, sorted(path.name for path in hook_dir.iterdir())) == (
            tmp_path / SPAWN_HOOK_DIRNAME,
            ['sitecustomize.py'],
        )

    def it_embeds_the_origin_finder_source(self) -> None:
        assert ascii(inspect.getsource(origin_finder)) in get_spawn_hook_script()


@pytest.mark.small
class DescribeExportSpawnHook:
    """A runner puts the hook first on ``PYTHONPATH`` for the process that may start spawn children."""

    def it_prepends_the_hook_directory_to_an_existing_python_path(self, tmp_path: Path) -> None:
        env = {SOURCES_FILE_ENV_VAR: str(tmp_path / 'sources.json'), 'PYTHONPATH': '/users/path'}

        export_spawn_hook(env)

        assert env['PYTHONPATH'] == os.pathsep.join([str(tmp_path / SPAWN_HOOK_DIRNAME), '/users/path'])

    @pytest.mark.parametrize('inherited', [pytest.param({}, id='unset'), pytest.param({'PYTHONPATH': ''}, id='empty')])
    def it_sets_the_python_path_when_there_was_none(self, tmp_path: Path, inherited: dict[str, str]) -> None:
        env = {SOURCES_FILE_ENV_VAR: str(tmp_path / 'sources.json'), **inherited}

        export_spawn_hook(env)

        assert env['PYTHONPATH'] == str(tmp_path / SPAWN_HOOK_DIRNAME)

    def it_does_not_prepend_the_hook_twice(self, tmp_path: Path) -> None:
        env = {SOURCES_FILE_ENV_VAR: str(tmp_path / 'sources.json')}

        export_spawn_hook(env)
        export_spawn_hook(env)

        assert env['PYTHONPATH'] == str(tmp_path / SPAWN_HOOK_DIRNAME)

    def it_leaves_the_environment_alone_without_a_sources_file(self) -> None:
        env = {'PYTHONPATH': '/users/path'}

        export_spawn_hook(env)

        assert env == {'PYTHONPATH': '/users/path'}
