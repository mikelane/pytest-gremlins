"""The in-process executor hosts the suite, so a spawn child it starts must inherit the active gremlin (#604)."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import types

import pytest

from pytest_gremlins.instrumentation.spawn_hook import (
    SOURCES_FILE_ENV_VAR,
    SPAWN_HOOK_DIRNAME,
)
from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor

TARGET = '_spawn_env_target'
TESTS = '_spawn_env_tests'
GREMLIN_DIR = Path(os.sep) / 'gremlin_dir'
SOURCES_FILE = str(GREMLIN_DIR / 'sources.json')
HOOK_DIR = str(GREMLIN_DIR / SPAWN_HOOK_DIRNAME)

RecordedEnvironments = list[dict[str, object]]


@pytest.fixture
def recorded_environments(monkeypatch: pytest.MonkeyPatch) -> RecordedEnvironments:
    """Install an instrumented module and a test that records what a spawn child would inherit."""
    recorded: RecordedEnvironments = []
    target = types.ModuleType(TARGET)
    target.__gremlin_active__ = None  # type: ignore[attr-defined]
    tests = types.ModuleType(TESTS)

    def test_records_environment() -> None:
        recorded.append(
            {
                'ACTIVE_GREMLIN': os.environ.get('ACTIVE_GREMLIN'),
                'PYTHONPATH': os.environ.get('PYTHONPATH'),
                'attribute': target.__gremlin_active__,  # type: ignore[attr-defined]
            }
        )

    tests.test_records_environment = test_records_environment  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, TARGET, target)
    monkeypatch.setitem(sys.modules, TESTS, tests)
    monkeypatch.setenv(SOURCES_FILE_ENV_VAR, SOURCES_FILE)
    monkeypatch.setenv('PYTHONPATH', '/users/path')
    monkeypatch.delenv('ACTIVE_GREMLIN', raising=False)
    return recorded


def _execute_gremlins(gremlin_ids: list[str]) -> None:
    InProcessExecutor().execute(gremlin_ids, dict.fromkeys(gremlin_ids, TARGET), [f'{TESTS}::test_records_environment'])


@pytest.mark.small
class DescribeInProcessExecutorExportsTheSpawnEnvironment:
    """While a gremlin is active, ``os.environ`` carries what a spawn child needs to run the same gremlin."""

    def it_exports_the_active_gremlin_and_the_hook_while_the_tests_run(
        self, recorded_environments: RecordedEnvironments
    ) -> None:
        _execute_gremlins(['g001'])

        assert [(entry['ACTIVE_GREMLIN'], entry['PYTHONPATH']) for entry in recorded_environments] == [
            ('g001', os.pathsep.join([HOOK_DIR, '/users/path']))
        ]

    def it_exports_each_gremlin_in_turn(self, recorded_environments: RecordedEnvironments) -> None:
        _execute_gremlins(['g001', 'g002'])

        assert [entry['ACTIVE_GREMLIN'] for entry in recorded_environments] == ['g001', 'g002']

    def it_restores_the_environment_afterwards(self, recorded_environments: RecordedEnvironments) -> None:
        _execute_gremlins(['g001'])

        assert (len(recorded_environments), os.environ.get('ACTIVE_GREMLIN'), os.environ['PYTHONPATH']) == (
            1,
            None,
            '/users/path',
        )

    def it_keeps_toggling_the_module_attribute(self, recorded_environments: RecordedEnvironments) -> None:
        _execute_gremlins(['g001'])

        assert [entry['attribute'] for entry in recorded_environments] == ['g001']
