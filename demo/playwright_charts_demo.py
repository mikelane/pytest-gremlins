#!/usr/bin/env python3
"""Epic C demo: Data Visualizations screenshots.

Captures screenshots of all four Chart.js chart types rendered in the
pytest-gremlins HTML report. Reports are loaded via file:// URLs with a
local copy of chart.umd.min.js so no CDN access is required.

Run from the worktree root:
    uv run python demo/playwright_charts_demo.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright


REPORT_NORMAL = Path('/tmp/gremlin-demo-epicc/report-normal/index.html')  # noqa: S108  # nosec B108
REPORT_PERFECT = Path('/tmp/perfect/report-perfect/index.html')  # noqa: S108  # nosec B108
OUT_DIR = Path(__file__).parent.parent / 'docs' / 'demo' / 'epic-c-charts'

# How long to wait after page load for Chart.js to finish drawing (ms)
CHART_RENDER_WAIT_MS = 4000

# Canvas IDs from src/pytest_gremlins/reporting/html.py
CANVASES = {
    'scoreGauge': '01-score-gauge.png',
    'outcomeChart': '02-outcome-pie.png',
    'fileChart': '03-file-bar.png',
    'operatorChart': '04-operator-chart.png',
}


def _load_report(page: Page, report_path: Path) -> None:
    """Navigate to a report and wait for Chart.js to finish rendering."""
    page.goto(report_path.resolve().as_uri())
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(CHART_RENDER_WAIT_MS)


def _screenshot_canvas(page: Page, canvas_id: str, out_path: Path) -> None:
    """Screenshot the chart card containing a canvas element.

    Finds the canvas by ID, reads its bounding box, then expands the clip
    region upward to include the card title. Falls back to full-page if
    the canvas cannot be located.
    """
    try:
        page.wait_for_selector(f'#{canvas_id}', state='attached', timeout=5000)
        box = page.locator(f'#{canvas_id}').bounding_box()
        if box is None:
            raise ValueError(f'#{canvas_id} has no bounding box')  # noqa: TRY301
        clip = {
            'x': max(0, box['x'] - 24),
            'y': max(0, box['y'] - 50),
            'width': box['width'] + 48,
            'height': box['height'] + 74,
        }
        page.screenshot(path=str(out_path), clip=clip, full_page=True)
        print(f'  {out_path.name}  ({out_path.stat().st_size // 1024} KB)')
    except Exception as exc:
        print(f'  WARNING: clipping #{canvas_id} failed ({exc}); using full-page fallback')
        page.screenshot(path=str(out_path), full_page=True)
        print(f'  {out_path.name}  (full-page, {out_path.stat().st_size // 1024} KB)')


def capture_normal_report(page: Page, out_dir: Path) -> None:
    """Capture score gauge, outcome pie, file bar, and operator charts."""
    print('Loading normal report...')
    _load_report(page, REPORT_NORMAL)
    for canvas_id, filename in CANVASES.items():
        _screenshot_canvas(page, canvas_id, out_dir / filename)


def capture_perfect_report(page: Page, out_dir: Path) -> None:
    """Capture the 100% score gauge from the perfect-score report."""
    print('Loading perfect-score report...')
    _load_report(page, REPORT_PERFECT)
    _screenshot_canvas(page, 'scoreGauge', out_dir / '05-perfect-score.png')


def main() -> None:
    """Capture Chart.js visualization screenshots from both demo reports."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for report, label in [(REPORT_NORMAL, 'normal'), (REPORT_PERFECT, 'perfect')]:
        if not report.exists():
            raise FileNotFoundError(f'{label} report not found: {report}')
        chartjs = report.parent / 'chart.umd.min.js'
        if not chartjs.exists():
            raise FileNotFoundError(
                f'chart.umd.min.js missing from {report.parent} — run: cp /tmp/chart.umd.min.js {report.parent}'  # nosec B108
            )

    print(f'Writing screenshots to {OUT_DIR}\n')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            device_scale_factor=2,
        )
        page = context.new_page()

        capture_normal_report(page, OUT_DIR)
        capture_perfect_report(page, OUT_DIR)

        context.close()
        browser.close()

    print('\nDone.')


if __name__ == '__main__':
    main()
