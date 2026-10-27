# ruff: noqa
import pytest

STATE = {'configured': 0, 'session_fixture_built': 0}


def pytest_configure(config) -> None:
    STATE['configured'] += 1


@pytest.fixture(scope='session')
def expensive():
    STATE['session_fixture_built'] += 1
    return {'calls': 0}
