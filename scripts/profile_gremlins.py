#!/usr/bin/env python
"""Profiling script for pytest-gremlins to measure execution phases.

This script instruments the mutation testing pipeline to collect detailed
timing information for each phase of execution.

Note: This is a diagnostic script, not part of the main library. Some lint
rules are relaxed for convenience (subprocess calls, dynamic imports, etc.)
"""
# ruff: noqa: S603, ANN401, PLR0915

from __future__ import annotations

import ast
import cProfile
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import pstats
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any, Self


# Ensure the local package is importable
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

# E402 is expected here - we need to modify sys.path before importing
from pytest_gremlins.coverage import CoverageCollector, TestSelector  # noqa: E402
from pytest_gremlins.instrumentation.transformer import get_default_registry, transform_source  # noqa: E402


if TYPE_CHECKING:
    from pytest_gremlins.operators import GremlinOperator


@dataclass
class TimingResult:
    """Timing result for a single phase."""

    phase: str
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfilingResults:
    """Complete profiling results for a mutation testing run."""

    phases: list[TimingResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_phase(self, phase: str, duration_ms: float, **details: Any) -> None:
        """Add a timing result for a phase."""
        self.phases.append(TimingResult(phase=phase, duration_ms=duration_ms, details=details))

    def get_phase(self, phase: str) -> TimingResult | None:
        """Get timing result for a specific phase."""
        for p in self.phases:
            if p.phase == phase:
                return p
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'phases': [{'phase': p.phase, 'duration_ms': p.duration_ms, 'details': p.details} for p in self.phases],
            'total_time_ms': self.total_time_ms,
            'metadata': self.metadata,
        }


class _Timer:
    """Context manager for timing a phase."""

    def __init__(self, name: str, results: ProfilingResults) -> None:
        self.name = name
        self.results = results
        self.start_time = 0.0
        self.details: dict[str, Any] = {}

    def __enter__(self) -> Self:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *_args: object) -> None:
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        self.results.add_phase(self.name, duration_ms, **self.details)


def time_phase(name: str, results: ProfilingResults) -> _Timer:
    """Create a context manager to time a phase."""
    return _Timer(name, results)


def discover_source_files(target_path: Path) -> dict[str, str]:
    """Discover Python source files to mutate."""
    source_files: dict[str, str] = {}

    if target_path.is_file() and target_path.suffix == '.py':
        try:
            source = target_path.read_text()
            ast.parse(source)
            source_files[str(target_path)] = source
        except (SyntaxError, OSError):
            pass
    elif target_path.is_dir():
        for py_file in target_path.rglob('*.py'):
            name = py_file.name
            if name.startswith('test_') or name.endswith('_test.py'):
                continue
            if name == 'conftest.py':
                continue
            if '__pycache__' in str(py_file):
                continue
            try:
                source = py_file.read_text()
                ast.parse(source)
                source_files[str(py_file)] = source
            except (SyntaxError, OSError):
                pass

    return source_files


def profile_mutation_testing(target_path: Path, test_path: Path) -> ProfilingResults:
    """Profile a complete mutation testing run with detailed phase timings."""
    results = ProfilingResults()
    total_start = time.perf_counter()

    results.metadata = {
        'target_path': str(target_path),
        'test_path': str(test_path),
        'python_version': sys.version,
    }

    # Phase 1: Source file discovery
    with time_phase('source_discovery', results) as timer:
        source_files = discover_source_files(target_path)
        timer.details['file_count'] = len(source_files)
        timer.details['total_lines'] = sum(s.count('\n') + 1 for s in source_files.values())

    # Phase 2: AST parsing and transformation (mutation generation)
    registry = get_default_registry()
    operators: list[GremlinOperator] = registry.get_all()
    all_gremlins = []
    all_asts = {}

    with time_phase('ast_transformation', results) as timer:
        parse_times = []
        transform_times = []

        for file_path, source in source_files.items():
            # Time parsing
            t0 = time.perf_counter()
            _tree = ast.parse(source)
            parse_time = (time.perf_counter() - t0) * 1000
            parse_times.append(parse_time)

            # Time transformation
            t0 = time.perf_counter()
            gremlins, instrumented_tree = transform_source(source, file_path, operators)
            transform_time = (time.perf_counter() - t0) * 1000
            transform_times.append(transform_time)

            all_gremlins.extend(gremlins)
            all_asts[file_path] = instrumented_tree

        timer.details['gremlin_count'] = len(all_gremlins)
        timer.details['avg_parse_time_ms'] = sum(parse_times) / len(parse_times) if parse_times else 0
        timer.details['avg_transform_time_ms'] = sum(transform_times) / len(transform_times) if transform_times else 0

    # Phase 3: AST unparsing (code generation)
    with time_phase('code_generation', results) as timer:
        unparse_times = []
        total_output_bytes = 0
        for tree in all_asts.values():
            t0 = time.perf_counter()
            instrumented_source = ast.unparse(tree)
            unparse_time = (time.perf_counter() - t0) * 1000
            unparse_times.append(unparse_time)
            total_output_bytes += len(instrumented_source.encode('utf-8'))

        timer.details['avg_unparse_time_ms'] = sum(unparse_times) / len(unparse_times) if unparse_times else 0
        timer.details['total_output_bytes'] = total_output_bytes

    # Phase 4: Test discovery (run pytest --collect-only)
    with time_phase('test_discovery', results) as timer:
        test_discovery_cmd = [
            sys.executable,
            '-m',
            'pytest',
            str(test_path),
            '--collect-only',
            '-q',
        ]
        t0 = time.perf_counter()
        result = subprocess.run(
            test_discovery_cmd, capture_output=True, text=True, cwd=str(project_root), timeout=60, check=False
        )
        discovery_time = (time.perf_counter() - t0) * 1000
        timer.details['pytest_collect_time_ms'] = discovery_time

        # Count tests from output
        test_lines = [line for line in result.stdout.splitlines() if '::' in line]
        timer.details['test_count'] = len(test_lines)

    # Phase 5: Coverage collection (run tests with coverage)
    with time_phase('coverage_collection', results) as timer:
        coverage_db = project_root / '.coverage.profile'
        coverage_db.unlink(missing_ok=True)

        coveragerc_path = project_root / '.coveragerc.profile'
        coveragerc_path.write_text('[run]\nsource = .\ndynamic_context = test_function\n')

        coverage_cmd = [
            sys.executable,
            '-m',
            'coverage',
            'run',
            f'--rcfile={coveragerc_path}',
            f'--data-file={coverage_db}',
            '-m',
            'pytest',
            str(test_path),
            '--tb=no',
            '-q',
        ]

        t0 = time.perf_counter()
        subprocess.run(coverage_cmd, capture_output=True, cwd=str(project_root), timeout=120, check=False)
        coverage_time = (time.perf_counter() - t0) * 1000
        timer.details['coverage_run_time_ms'] = coverage_time

        # Parse coverage database
        t0 = time.perf_counter()

        try:
            with sqlite3.connect(str(coverage_db)) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM context WHERE context != ""')
                context_count = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM file')
                file_count = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM line_bits')
                line_bits_count = cursor.fetchone()[0]
                timer.details['context_count'] = context_count
                timer.details['covered_file_count'] = file_count
                timer.details['line_bits_entries'] = line_bits_count
        except Exception as e:
            timer.details['coverage_parse_error'] = str(e)

        parse_time = (time.perf_counter() - t0) * 1000
        timer.details['coverage_parse_time_ms'] = parse_time

        # Cleanup
        coverage_db.unlink(missing_ok=True)
        coveragerc_path.unlink(missing_ok=True)

    # Phase 6: Test selector building
    with time_phase('test_selector_build', results) as timer:
        # Simulate building test selector (would be done with real coverage data)
        collector = CoverageCollector()
        # Build a minimal map for timing
        t0 = time.perf_counter()
        _selector = TestSelector(collector.coverage_map)
        selector_time = (time.perf_counter() - t0) * 1000
        timer.details['selector_build_time_ms'] = selector_time

    # Phase 7: Per-mutation subprocess execution sampling
    # Run just a few gremlins to measure per-mutation overhead
    with time_phase('mutation_execution_sample', results) as timer:
        sample_size = min(5, len(all_gremlins))
        if sample_size > 0:
            subprocess_times = []

            # Write instrumented sources to temp file
            temp_dir = Path(tempfile.mkdtemp(prefix='pytest_gremlins_profile_'))
            sources_file = temp_dir / 'sources.json'
            sources_file.write_text('{}')  # Minimal sources

            for _i, gremlin in enumerate(all_gremlins[:sample_size]):
                # Simple test command (just running pytest discovery for timing)
                test_cmd = [
                    sys.executable,
                    '-m',
                    'pytest',
                    str(test_path),
                    '--collect-only',
                    '-q',
                ]

                env = os.environ.copy()
                env['ACTIVE_GREMLIN'] = gremlin.gremlin_id

                t0 = time.perf_counter()
                subprocess.run(test_cmd, capture_output=True, cwd=str(project_root), timeout=30, check=False, env=env)
                subprocess_time = (time.perf_counter() - t0) * 1000
                subprocess_times.append(subprocess_time)

            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

            timer.details['sample_size'] = sample_size
            timer.details['avg_subprocess_startup_ms'] = sum(subprocess_times) / len(subprocess_times)
            timer.details['min_subprocess_startup_ms'] = min(subprocess_times)
            timer.details['max_subprocess_startup_ms'] = max(subprocess_times)
            timer.details['total_subprocess_time_ms'] = sum(subprocess_times)

    results.total_time_ms = (time.perf_counter() - total_start) * 1000

    return results


def run_cprofile_analysis(target_path: Path, output_dir: Path) -> Path:
    """Run cProfile analysis and save results."""
    profiler = cProfile.Profile()

    # Profile the core transformation logic
    profiler.enable()

    source_files = discover_source_files(target_path)
    registry = get_default_registry()
    operators: list[GremlinOperator] = registry.get_all()

    for file_path, source in source_files.items():
        transform_source(source, file_path, operators)

    profiler.disable()

    # Save stats
    stats_file = output_dir / 'profile.pstats'
    profiler.dump_stats(str(stats_file))

    # Generate human-readable report
    stats_report = output_dir / 'profile_stats.txt'
    with stats_report.open('w') as f:
        ps = pstats.Stats(profiler, stream=f)
        ps.strip_dirs()
        ps.sort_stats('cumulative')
        ps.print_stats(50)
        f.write('\n\n--- Sorted by Internal Time ---\n\n')
        ps.sort_stats('tottime')
        ps.print_stats(50)

    return stats_report


def main() -> ProfilingResults:
    """Main entry point for profiling."""
    target_path = project_root / 'src' / 'pytest_gremlins'
    test_path = project_root / 'tests'
    output_dir = project_root / 'docs' / 'performance'
    output_dir.mkdir(parents=True, exist_ok=True)

    print('=' * 60)
    print('pytest-gremlins Profiling Analysis')
    print('=' * 60)
    print(f'Target: {target_path}')
    print(f'Tests: {test_path}')
    print()

    # Run detailed phase profiling
    print('Running phase-by-phase profiling...')
    results = profile_mutation_testing(target_path, test_path)

    # Save JSON results
    json_output = output_dir / 'profiling_data.json'
    with json_output.open('w') as f:
        json.dump(results.to_dict(), f, indent=2)
    print(f'JSON results saved to: {json_output}')

    # Run cProfile analysis
    print('\nRunning cProfile analysis...')
    stats_report = run_cprofile_analysis(target_path, output_dir)
    print(f'cProfile stats saved to: {stats_report}')

    # Print summary
    print('\n' + '=' * 60)
    print('PROFILING SUMMARY')
    print('=' * 60)
    print(f'Total profiling time: {results.total_time_ms:.2f}ms')
    print()
    print('Phase breakdown:')
    print('-' * 60)

    for phase in results.phases:
        pct = (phase.duration_ms / results.total_time_ms * 100) if results.total_time_ms > 0 else 0
        print(f'{phase.phase:<30} {phase.duration_ms:>10.2f}ms  ({pct:>5.1f}%)')
        for key, value in phase.details.items():
            if isinstance(value, float):
                print(f'  - {key}: {value:.2f}')
            else:
                print(f'  - {key}: {value}')

    return results


if __name__ == '__main__':
    main()
