"""Gremlin runs and the coverage pre-scan read the session's ``-c`` config file (#951).

A config file with a name pytest does not discover on its own (``gremlin.ini``) was never given to the child
sessions.  Without its ``pythonpath`` they could not import the project, and every gremlin scored ERROR with
"found no collectors".
"""

from __future__ import annotations

import configparser
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins import verdicts as verdicts_module

STRONG_TEST = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

SCORED_VERDICTS = {'Zapped': 2, 'Survived': 0, 'Error': 0}


@pytest.fixture(autouse=True)
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest processes write UTF-8 so the parent decodes their output on any platform."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.fixture
def project(pytester_with_markers: pytest.Pytester) -> Path:
    """A project whose only config is ``gremlin.ini``, which holds the ``pythonpath`` the tests need."""
    root = pytester_with_markers.path
    (root / 'gremlin.ini').write_text('[pytest]\npythonpath = src\n', encoding='utf-8')
    (root / 'src').mkdir()
    (root / 'src' / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    (root / 'tests').mkdir()
    (root / 'tests' / 'test_sample.py').write_text(STRONG_TEST, encoding='utf-8')
    return root


@pytest.mark.medium
class DescribeAConfigFileGivenWithDashC:
    def it_scores_gremlins_when_the_config_file_has_a_name_pytest_does_not_discover(
        self, pytester_with_markers: pytest.Pytester, project: Path
    ) -> None:
        target = f'--gremlin-targets={(project / "src" / "sample.py").as_posix()}'

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, target, '-c', (project / 'gremlin.ini').as_posix(), 'tests'
        )

        assert verdicts(result.stdout.str()) == SCORED_VERDICTS, result.stdout.str() + result.stderr.str()


def _session_config(
    rootdir: Path, inipath: Path | None, *, given_config_file: str | None = None, confcutdir: str | None = None
) -> pytest.Config:
    """A session config as pytest resolves it: the ``confcutdir`` defaults to the config file's directory."""
    default_confcutdir = inipath.parent if inipath else rootdir
    resolved_confcutdir = confcutdir or default_confcutdir.as_posix()
    return cast(
        'pytest.Config',
        SimpleNamespace(
            option=SimpleNamespace(inifilename=given_config_file),
            inipath=inipath,
            rootpath=rootdir,
            known_args_namespace=SimpleNamespace(confcutdir=resolved_confcutdir),
            invocation_params=SimpleNamespace(dir=rootdir),
        ),
    )


@pytest.mark.small
class DescribeTheConfigFileOptions:
    def it_names_the_config_file_the_session_was_given(self, tmp_path: Path) -> None:
        ini = tmp_path / 'gremlin.ini'
        config = _session_config(tmp_path, ini, given_config_file=str(ini))

        assert plugin._config_file_options(config)[:2] == ['-c', ini.as_posix()]

    def it_names_the_config_file_the_session_discovered(self, tmp_path: Path) -> None:
        discovered = tmp_path / 'pytest.ini'
        config = _session_config(tmp_path, discovered)

        assert plugin._config_file_options(config)[:2] == ['-c', discovered.as_posix()]

    def it_pins_the_rootdir_and_confcutdir_of_a_session_without_a_config_file(self, tmp_path: Path) -> None:
        config = _session_config(tmp_path, None)

        assert plugin._config_file_options(config)[2:] == [
            f'--rootdir={tmp_path.as_posix()}',
            f'--confcutdir={tmp_path.as_posix()}',
        ]

    def it_pins_the_confcutdir_the_session_was_given_rather_than_the_config_file_directory(
        self, tmp_path: Path
    ) -> None:
        config = _session_config(tmp_path, tmp_path / 'pkg1' / 'pytest.ini', confcutdir='lib')

        assert plugin._config_file_options(config)[3] == f'--confcutdir={(tmp_path / "lib").as_posix()}'

    def it_puts_the_config_file_in_a_gremlin_run_command_once(self) -> None:
        command = verdicts_module._build_test_command(None, '', config_file_options=['-c', 'gremlin.ini'])

        assert command.count('-c') == 1
        assert command[command.index('-c') + 1] == 'gremlin.ini'


@pytest.mark.medium
class DescribeTheFileGivenWhenTheSessionReadNoConfigFile:
    def it_names_a_file_without_settings_when_the_session_read_no_config_file(self, tmp_path: Path) -> None:
        config = _session_config(tmp_path, None)

        no_config_file = Path(plugin._config_file_options(config)[1])
        sections = configparser.ConfigParser()
        sections.read(no_config_file, encoding='utf-8')

        assert no_config_file.is_file()
        assert sections.sections() == []


@pytest.mark.medium
class DescribeThePrescanCommand:
    def it_puts_the_config_file_in_the_prescan_command_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launched: list[list[str]] = []
        monkeypatch.setattr(plugin, '_launch_prescan', lambda cmd, *_args: launched.append(cmd))

        plugin._run_tests_with_coverage([], tmp_path, config_file_options=['-c', 'gremlin.ini'])

        assert launched[0].count('-c') == 1
        assert launched[0][launched[0].index('-c') + 1] == 'gremlin.ini'
