#!/usr/bin/env python3
r"""Upload mutation testing results to Stryker Dashboard.

This script converts pytest-gremlins JSON output to Stryker format
and uploads it to the Stryker Dashboard for badge display and
report hosting.

Usage:
    # Set your API key
    export STRYKER_DASHBOARD_API_KEY=your_key

    # Upload to dashboard
    python upload_to_stryker_dashboard.py \
        --input gremlin-report.json \
        --project github.com/owner/repo \
        --version main

Requirements:
    - requests (for HTTP upload)
    - pytest-gremlins (for exporters)

See: https://dashboard.stryker-mutator.io/
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


try:
    import requests
except ImportError:
    print('Error: requests package required. Install with: pip install requests')
    sys.exit(1)


DASHBOARD_URL = 'https://dashboard.stryker-mutator.io/api/reports'
HTTP_OK = 200


def convert_to_stryker_format(input_path: Path) -> str:
    """Convert pytest-gremlins JSON to Stryker format.

    Note: This is a simplified conversion that creates a score-only report.
    For full reports, the StrykerExporter should be used during test execution.

    Args:
        input_path: Path to gremlin-report.json

    Returns:
        JSON string in Stryker score-only format.
    """
    with input_path.open() as f:
        data = json.load(f)

    # Extract mutation score
    score = data['summary']['percentage']

    # Return score-only format (sufficient for badge)
    return json.dumps({'mutationScore': score})


def upload_to_dashboard(
    report_json: str,
    project: str,
    version: str,
    api_key: str,
    module: str | None = None,
) -> bool:
    """Upload mutation report to Stryker Dashboard.

    Args:
        report_json: JSON string of the mutation report.
        project: Project identifier (e.g., 'github.com/owner/repo').
        version: Version/branch name (e.g., 'main' or 'feature/foo').
        api_key: Stryker Dashboard API key.
        module: Optional module name for multi-module projects.

    Returns:
        True if upload succeeded, False otherwise.
    """
    url = f'{DASHBOARD_URL}/{project}/{version}'
    if module:
        url += f'?module={module}'

    headers = {
        'Content-Type': 'application/json',
        'X-Api-Key': api_key,
    }

    response = requests.put(url, data=report_json, headers=headers, timeout=30)

    if response.status_code == HTTP_OK:
        print(f'Successfully uploaded to {url}')
        return True

    print(f'Upload failed: {response.status_code} - {response.text}')
    return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Upload mutation testing results to Stryker Dashboard',
    )
    parser.add_argument(
        '--input',
        '-i',
        type=Path,
        default=Path('gremlin-report.json'),
        help='Path to gremlin-report.json (default: gremlin-report.json)',
    )
    parser.add_argument(
        '--project',
        '-p',
        required=True,
        help='Project identifier (e.g., github.com/owner/repo)',
    )
    parser.add_argument(
        '--version',
        '-v',
        required=True,
        help='Version/branch name (e.g., main)',
    )
    parser.add_argument(
        '--module',
        '-m',
        help='Optional module name for multi-module projects',
    )
    parser.add_argument(
        '--api-key',
        help='Stryker Dashboard API key (default: STRYKER_DASHBOARD_API_KEY env var)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Generate Stryker format without uploading',
    )

    args = parser.parse_args()

    # Get API key
    api_key = args.api_key or os.environ.get('STRYKER_DASHBOARD_API_KEY')
    if not api_key and not args.dry_run:
        print('Error: API key required. Set STRYKER_DASHBOARD_API_KEY or use --api-key')
        return 1

    # Check input file exists
    if not args.input.exists():
        print(f'Error: Input file not found: {args.input}')
        return 1

    # Convert to Stryker format
    print(f'Converting {args.input} to Stryker format...')
    report_json = convert_to_stryker_format(args.input)

    if args.dry_run:
        print('Dry run - would upload:')
        print(report_json)
        return 0

    # Upload to dashboard
    success = upload_to_dashboard(
        report_json=report_json,
        project=args.project,
        version=args.version,
        api_key=api_key,
        module=args.module,
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
