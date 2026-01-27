"""Tests for the benchmark regression check script.

These tests verify that the regression detection logic works correctly,
catching significant performance regressions while allowing normal variance.
"""

from pathlib import Path
import sys
import tempfile

import pytest


# Add benchmarks directory to path for imports (needed for runtime)
_benchmarks_path = str(Path(__file__).parents[2] / 'benchmarks')
if _benchmarks_path not in sys.path:
    sys.path.insert(0, _benchmarks_path)

# Import will fail until we implement check_regression.py
from benchmarks.check_regression import (  # noqa: E402
    RegressionCheckResult,
    RegressionDetail,
    check_regression,
    load_benchmark_results,
)


@pytest.mark.small
class TestRegressionDetail:
    def test_regression_detail_creation(self):
        detail = RegressionDetail(
            config='gremlins_sequential',
            baseline_time=10.0,
            current_time=12.0,
            change_percent=20.0,
        )
        assert detail.config == 'gremlins_sequential'
        assert detail.baseline_time == 10.0
        assert detail.current_time == 12.0
        assert detail.change_percent == 20.0

    def test_regression_detail_str_positive_change(self):
        detail = RegressionDetail(
            config='gremlins_parallel',
            baseline_time=5.0,
            current_time=6.0,
            change_percent=20.0,
        )
        result = str(detail)
        assert 'gremlins_parallel' in result
        assert '5.00s' in result
        assert '6.00s' in result
        assert '+20.0%' in result

    def test_regression_detail_str_negative_change(self):
        detail = RegressionDetail(
            config='gremlins_full',
            baseline_time=10.0,
            current_time=8.0,
            change_percent=-20.0,
        )
        result = str(detail)
        assert '-20.0%' in result


@pytest.mark.small
class TestRegressionCheckResult:
    def test_check_result_no_regressions(self):
        result = RegressionCheckResult(
            has_regressions=False,
            regressions=[],
            improvements=[],
            threshold_percent=10.0,
        )
        assert not result.has_regressions
        assert result.regressions == []
        assert result.threshold_percent == 10.0

    def test_check_result_with_regressions(self):
        regression = RegressionDetail(
            config='gremlins_sequential',
            baseline_time=10.0,
            current_time=15.0,
            change_percent=50.0,
        )
        result = RegressionCheckResult(
            has_regressions=True,
            regressions=[regression],
            improvements=[],
            threshold_percent=10.0,
        )
        assert result.has_regressions
        assert len(result.regressions) == 1

    def test_check_result_with_improvements(self):
        improvement = RegressionDetail(
            config='gremlins_parallel',
            baseline_time=10.0,
            current_time=5.0,
            change_percent=-50.0,
        )
        result = RegressionCheckResult(
            has_regressions=False,
            regressions=[],
            improvements=[improvement],
            threshold_percent=10.0,
        )
        assert not result.has_regressions
        assert len(result.improvements) == 1


@pytest.mark.small
class TestCheckRegression:
    def test_no_regression_within_threshold(self):
        baseline = {
            'gremlins_sequential': 45.63,
            'gremlins_parallel': 10.36,
            'mutmut_default': 37.22,
        }
        current = {
            'gremlins_sequential': 46.0,  # +0.8% change, within 10%
            'gremlins_parallel': 10.5,  # +1.4% change, within 10%
            'mutmut_default': 38.0,  # +2.1% change, within 10%
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert not result.has_regressions
        assert result.regressions == []

    def test_regression_exceeds_threshold(self):
        baseline = {
            'gremlins_sequential': 45.63,
            'gremlins_parallel': 10.36,
        }
        current = {
            'gremlins_sequential': 55.0,  # +20.5% change, exceeds 10%
            'gremlins_parallel': 10.5,  # +1.4% change, within 10%
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert result.has_regressions
        assert len(result.regressions) == 1
        assert result.regressions[0].config == 'gremlins_sequential'

    def test_multiple_regressions(self):
        baseline = {
            'gremlins_sequential': 45.63,
            'gremlins_parallel': 10.36,
            'gremlins_full': 11.42,
        }
        current = {
            'gremlins_sequential': 55.0,  # +20.5% regression
            'gremlins_parallel': 15.0,  # +44.8% regression
            'gremlins_full': 12.0,  # +5.1% OK
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert result.has_regressions
        assert len(result.regressions) == 2
        configs = {r.config for r in result.regressions}
        assert configs == {'gremlins_sequential', 'gremlins_parallel'}

    def test_improvement_detected(self):
        baseline = {
            'gremlins_sequential': 45.63,
            'gremlins_parallel': 10.36,
        }
        current = {
            'gremlins_sequential': 30.0,  # -34.3% improvement
            'gremlins_parallel': 10.5,  # +1.4% within threshold
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert not result.has_regressions
        assert len(result.improvements) == 1
        assert result.improvements[0].config == 'gremlins_sequential'
        assert result.improvements[0].change_percent < 0

    def test_missing_config_in_current_ignored(self):
        baseline = {
            'gremlins_sequential': 45.63,
            'gremlins_parallel': 10.36,
            'gremlins_full': 11.42,
        }
        current = {
            'gremlins_sequential': 46.0,
            'gremlins_parallel': 10.5,
            # gremlins_full missing - should be ignored
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert not result.has_regressions

    def test_extra_config_in_current_ignored(self):
        baseline = {
            'gremlins_sequential': 45.63,
        }
        current = {
            'gremlins_sequential': 46.0,
            'gremlins_parallel': 10.5,  # Not in baseline, should be ignored
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert not result.has_regressions

    def test_exact_threshold_not_regression(self):
        baseline = {
            'gremlins_sequential': 100.0,
        }
        current = {
            'gremlins_sequential': 110.0,  # Exactly 10% change
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        # Exactly at threshold should NOT be a regression (> not >=)
        assert not result.has_regressions

    def test_just_over_threshold_is_regression(self):
        baseline = {
            'gremlins_sequential': 100.0,
        }
        current = {
            'gremlins_sequential': 110.01,  # Just over 10%
        }
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert result.has_regressions

    def test_custom_threshold(self):
        baseline = {
            'gremlins_sequential': 100.0,
        }
        current = {
            'gremlins_sequential': 115.0,  # 15% change
        }
        # With 20% threshold, this should NOT be a regression
        result = check_regression(baseline, current, threshold_percent=20.0)
        assert not result.has_regressions

        # With 10% threshold, this SHOULD be a regression
        result = check_regression(baseline, current, threshold_percent=10.0)
        assert result.has_regressions


@pytest.mark.small
class TestLoadBenchmarkResults:
    def test_load_valid_json_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"gremlins_sequential": 45.63, "gremlins_parallel": 10.36}')
            f.flush()

            result = load_benchmark_results(Path(f.name))
            assert result == {
                'gremlins_sequential': 45.63,
                'gremlins_parallel': 10.36,
            }

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_benchmark_results(Path('/nonexistent/path.json'))

    def test_load_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('not valid json {')
            f.flush()

            with pytest.raises(ValueError, match='Invalid JSON'):
                load_benchmark_results(Path(f.name))

    def test_load_from_full_results_format(self):
        # The benchmark runner outputs a more complex format with summaries
        # We need to extract just the timing data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("""
            {
                "environment": {"platform": "Linux"},
                "summaries": [
                    {"tool": "gremlins", "config": "sequential", "mean_time": 45.63},
                    {"tool": "gremlins", "config": "parallel", "mean_time": 10.36},
                    {"tool": "mutmut", "config": "default", "mean_time": 37.22}
                ],
                "results": []
            }
            """)
            f.flush()

            result = load_benchmark_results(Path(f.name))
            assert result == {
                'gremlins_sequential': 45.63,
                'gremlins_parallel': 10.36,
                'mutmut_default': 37.22,
            }

    def test_load_from_simple_format(self):
        # Simple key-value format for baseline.json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"gremlins_sequential": 45.63}')
            f.flush()

            result = load_benchmark_results(Path(f.name))
            assert result == {'gremlins_sequential': 45.63}
