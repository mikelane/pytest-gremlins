"""``_gremlin_runs_load_pytest_cov`` decides whether gremlin runs know ``--no-cov`` (issue #684)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _gremlin_runs_load_pytest_cov

SKIPS_AUTOLOAD = ['--disable-plugin-autoload', '-p', 'pytest_rerunfailures']


@pytest.mark.small
class DescribeGremlinRunsLoadPytestCov:
    def it_is_true_when_gremlin_runs_autoload_their_plugins(self) -> None:
        assert _gremlin_runs_load_pytest_cov('', ['--reruns', '2']) is True

    def it_is_false_when_the_rerun_options_skip_autoload_and_nothing_loads_it(self) -> None:
        assert _gremlin_runs_load_pytest_cov('-q', SKIPS_AUTOLOAD) is False

    @pytest.mark.parametrize('addopts', ['-p pytest_cov.plugin', '-ppytest_cov', '-q -p pytest_cov'])
    def it_is_true_when_addopts_load_it(self, addopts: str) -> None:
        assert _gremlin_runs_load_pytest_cov(addopts, SKIPS_AUTOLOAD) is True

    def it_is_true_when_pytest_plugins_loads_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_PLUGINS', 'other,pytest_cov.plugin')

        assert _gremlin_runs_load_pytest_cov('', SKIPS_AUTOLOAD) is True

    def it_is_false_for_an_unrelated_loader(self) -> None:
        assert _gremlin_runs_load_pytest_cov('-p pytest_rerunfailures', SKIPS_AUTOLOAD) is False
