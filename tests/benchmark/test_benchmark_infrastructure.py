"""Tests for the benchmark infrastructure.

These tests verify that the benchmark utilities work correctly,
not that pytest-gremlins is faster than mutmut (that's what
the actual benchmarks are for).
"""

from pathlib import Path
import sys
import tempfile

import pytest


# Add benchmarks directory to path for imports
sys.path.insert(0, str(Path(__file__).parents[2] / 'benchmarks'))

from run_benchmarks import (
    BenchmarkResult,
    BenchmarkSummary,
    EnvironmentInfo,
    compute_summaries,
    create_synthetic_project,
    generate_markdown_report,
)


@pytest.mark.small
class TestBenchmarkResult:
    def test_benchmark_result_creation(self):
        result = BenchmarkResult(
            tool='gremlins',
            project='synthetic',
            config='sequential',
            wall_time_seconds=10.5,
            mutations_total=100,
            mutations_killed=80,
        )
        assert result.tool == 'gremlins'
        assert result.project == 'synthetic'
        assert result.config == 'sequential'
        assert result.wall_time_seconds == 10.5
        assert result.mutations_total == 100
        assert result.mutations_killed == 80
        assert result.error is None

    def test_benchmark_result_with_error(self):
        result = BenchmarkResult(
            tool='mutmut',
            project='synthetic',
            config='default',
            wall_time_seconds=0,
            error='Timeout after 600 seconds',
        )
        assert result.error == 'Timeout after 600 seconds'
        assert result.wall_time_seconds == 0


@pytest.mark.small
class TestBenchmarkSummary:
    def test_benchmark_summary_creation(self):
        summary = BenchmarkSummary(
            tool='gremlins',
            project='synthetic',
            config='parallel',
            mean_time=5.5,
            stddev_time=0.3,
            min_time=5.0,
            max_time=6.0,
            mutations_total=100,
            mutations_killed=85,
            runs=3,
        )
        assert summary.tool == 'gremlins'
        assert summary.mean_time == 5.5
        assert summary.stddev_time == 0.3
        assert summary.runs == 3


@pytest.mark.small
class TestEnvironmentInfo:
    def test_environment_info_creation(self):
        info = EnvironmentInfo(
            timestamp='2024-01-15T12:00:00',
            platform='Darwin 24.0.0',
            python_version='3.12.1',
            cpu_info='Apple M1',
            cpu_count=8,
            memory_gb=16.0,
        )
        assert info.platform == 'Darwin 24.0.0'
        assert info.cpu_count == 8
        assert info.mutmut_version == 'unknown'
        assert info.gremlins_version == 'unknown'


@pytest.mark.small
class TestComputeSummaries:
    def test_compute_summaries_single_config(self):
        results = [
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=10.0,
                mutations_total=100,
                mutations_killed=80,
                run_number=1,
            ),
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=12.0,
                mutations_total=100,
                mutations_killed=80,
                run_number=2,
            ),
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=11.0,
                mutations_total=100,
                mutations_killed=80,
                run_number=3,
            ),
        ]

        summaries = compute_summaries(results)
        assert len(summaries) == 1

        summary = summaries[0]
        assert summary.tool == 'gremlins'
        assert summary.config == 'sequential'
        assert summary.mean_time == 11.0  # (10 + 12 + 11) / 3
        assert summary.min_time == 10.0
        assert summary.max_time == 12.0
        assert summary.runs == 3

    def test_compute_summaries_multiple_configs(self):
        results = [
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=10.0,
                mutations_total=100,
                mutations_killed=80,
            ),
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='parallel',
                wall_time_seconds=5.0,
                mutations_total=100,
                mutations_killed=80,
            ),
            BenchmarkResult(
                tool='mutmut',
                project='synthetic',
                config='default',
                wall_time_seconds=20.0,
                mutations_total=100,
                mutations_killed=75,
            ),
        ]

        summaries = compute_summaries(results)
        assert len(summaries) == 3

        tools = {s.tool for s in summaries}
        assert tools == {'gremlins', 'mutmut'}

    def test_compute_summaries_skips_errors(self):
        results = [
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=10.0,
                mutations_total=100,
                mutations_killed=80,
            ),
            BenchmarkResult(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                wall_time_seconds=0,
                error='Timeout',
            ),
        ]

        summaries = compute_summaries(results)
        assert len(summaries) == 1
        assert summaries[0].runs == 1
        assert summaries[0].mean_time == 10.0


@pytest.mark.small
class TestGenerateMarkdownReport:
    def test_generate_report_includes_environment(self):
        env_info = EnvironmentInfo(
            timestamp='2024-01-15T12:00:00',
            platform='Darwin 24.0.0',
            python_version='3.12.1',
            cpu_info='Apple M1',
            cpu_count=8,
            memory_gb=16.0,
            mutmut_version='2.4.5',
            gremlins_version='0.1.0',
        )
        summaries = []
        results = []

        report = generate_markdown_report(env_info, summaries, results)

        assert 'Darwin 24.0.0' in report
        assert '3.12.1' in report
        assert 'Apple M1' in report
        assert '8 cores' in report
        assert '2.4.5' in report
        assert '0.1.0' in report

    def test_generate_report_includes_summary_table(self):
        env_info = EnvironmentInfo(
            timestamp='2024-01-15T12:00:00',
            platform='Darwin',
            python_version='3.12',
            cpu_info='CPU',
            cpu_count=8,
            memory_gb=16.0,
        )
        summaries = [
            BenchmarkSummary(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                mean_time=10.0,
                stddev_time=0.5,
                min_time=9.5,
                max_time=10.5,
                mutations_total=100,
                mutations_killed=80,
                runs=3,
            ),
        ]
        results = []

        report = generate_markdown_report(env_info, summaries, results)

        assert '| Tool | Config |' in report
        assert 'gremlins' in report
        assert 'sequential' in report
        assert '10.00s' in report

    def test_generate_report_includes_speedup_analysis(self):
        env_info = EnvironmentInfo(
            timestamp='2024-01-15T12:00:00',
            platform='Darwin',
            python_version='3.12',
            cpu_info='CPU',
            cpu_count=8,
            memory_gb=16.0,
        )
        summaries = [
            BenchmarkSummary(
                tool='mutmut',
                project='synthetic',
                config='default',
                mean_time=20.0,
                stddev_time=1.0,
                min_time=19.0,
                max_time=21.0,
                mutations_total=100,
                mutations_killed=75,
                runs=3,
            ),
            BenchmarkSummary(
                tool='gremlins',
                project='synthetic',
                config='sequential',
                mean_time=10.0,
                stddev_time=0.5,
                min_time=9.5,
                max_time=10.5,
                mutations_total=100,
                mutations_killed=80,
                runs=3,
            ),
        ]
        results = []

        report = generate_markdown_report(env_info, summaries, results)

        assert 'Speedup Analysis' in report
        assert 'Baseline' in report
        assert '2.0x' in report  # 20 / 10 = 2x speedup


@pytest.mark.medium
class TestCreateSyntheticProject:
    def test_create_synthetic_project_structure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)

            # Check directory structure
            assert project_dir.exists()
            assert (project_dir / 'src' / 'synthetic').is_dir()
            assert (project_dir / 'tests').is_dir()
            assert (project_dir / 'pyproject.toml').is_file()

    def test_create_synthetic_project_source_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)

            src_dir = project_dir / 'src' / 'synthetic'
            assert (src_dir / '__init__.py').is_file()
            assert (src_dir / 'calculator.py').is_file()
            assert (src_dir / 'validator.py').is_file()
            assert (src_dir / 'processor.py').is_file()

    def test_create_synthetic_project_test_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)

            test_dir = project_dir / 'tests'
            assert (test_dir / 'test_calculator.py').is_file()
            assert (test_dir / 'test_validator.py').is_file()
            assert (test_dir / 'test_processor.py').is_file()

    def test_synthetic_project_source_is_valid_python(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)

            src_dir = project_dir / 'src' / 'synthetic'
            for py_file in src_dir.glob('*.py'):
                source = py_file.read_text()
                # This will raise SyntaxError if invalid
                compile(source, str(py_file), 'exec')

    def test_synthetic_project_tests_are_valid_python(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)

            test_dir = project_dir / 'tests'
            for py_file in test_dir.glob('*.py'):
                source = py_file.read_text()
                # This will raise SyntaxError if invalid
                compile(source, str(py_file), 'exec')
