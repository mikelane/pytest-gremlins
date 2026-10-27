from conftest import STATE

MODULE_COUNTER = {'n': 0}


def test_plain() -> None:
    assert 1 + 1 == 2


def test_module_state_is_fresh() -> None:
    MODULE_COUNTER['n'] += 1
    assert MODULE_COUNTER['n'] == 1


def test_session_fixture_is_fresh(expensive) -> None:
    expensive['calls'] += 1
    assert expensive['calls'] == 1


def test_conftest_state_is_fresh() -> None:
    assert STATE['configured'] == 1
    assert STATE['session_fixture_built'] <= 1


def test_env_toggle_is_read_per_run(monkeypatch) -> None:
    import os

    assert os.environ.get('ACTIVE_GREMLIN') is None
