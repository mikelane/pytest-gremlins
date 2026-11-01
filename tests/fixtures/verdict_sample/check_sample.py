import pytest
import sample

_attempts_seen: list[bool] = []


def test_is_adult():
    assert sample.is_adult(18) is True
    assert sample.is_adult(17) is False


def test_both():
    assert sample.both(True, False) is False
    assert sample.both(True, True) is True


def test_total():
    assert sample.total(3, 4) == 12


def test_is_smaller_only_runs_it():
    assert sample.is_smaller(1, 2)


def test_count_down():
    assert sample.count_down(3) == 0


@pytest.mark.parametrize('level', sample.LEVELS)
def test_double(level):
    assert sample.double(level) == 4


def test_is_retry_safe_fails_its_first_attempt():
    _attempts_seen.append(sample.is_retry_safe(1))
    assert len(_attempts_seen) > 1
