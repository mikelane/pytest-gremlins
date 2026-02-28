#!/usr/bin/env python3
"""Epic F capstone demo: comprehensive Rich HTML Reports walkthrough.

Captures eight screenshots of the pytest-gremlins HTML report covering
the full feature set: dark/light theme toggle, all four Chart.js
visualisations, code diff panels, and the full report overview.

Run from the worktree root:
    uv run python demo/capstone/playwright_capstone_demo.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright


_REPORT_PATH = Path('/tmp/gremlin-demo-epicf/report/index.html')  # noqa: S108  # nosec B108
_OUT_DIR = Path(__file__).parent.parent.parent / 'docs' / 'demo' / 'epic-f-capstone'

_CHART_RENDER_WAIT_MS = 4000
_THEME_SETTLE_MS = 500

_CANVAS_IDS = {
    'scoreGauge': '03-score-gauge.png',
    'outcomeChart': '04-outcome-pie.png',
    'fileChart': '05-file-bar.png',
    'operatorChart': '06-operator-chart.png',
}


def _load_report(page: Page) -> None:
    """Navigate to the demo report and wait for Chart.js to finish rendering."""
    page.goto(_REPORT_PATH.resolve().as_uri())
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(_CHART_RENDER_WAIT_MS)


def _screenshot_dark_mode(page: Page) -> None:
    """Capture the default dark-mode full-page screenshot."""
    page.screenshot(path=str(_OUT_DIR / '01-dark-mode.png'), full_page=True)
    print(f'  01-dark-mode.png  ({(_OUT_DIR / "01-dark-mode.png").stat().st_size // 1024} KB)')


def _screenshot_light_mode(page: Page) -> None:
    """Toggle to light mode and capture the full-page screenshot."""
    page.click('button.theme-toggle')
    page.wait_for_timeout(_THEME_SETTLE_MS)
    page.screenshot(path=str(_OUT_DIR / '02-light-mode.png'), full_page=True)
    print(f'  02-light-mode.png  ({(_OUT_DIR / "02-light-mode.png").stat().st_size // 1024} KB)')
    # Return to dark mode for the chart screenshots
    page.click('button.theme-toggle')
    page.wait_for_timeout(_THEME_SETTLE_MS)


def _clip_canvas(page: Page, canvas_id: str, out_path: Path) -> None:
    """Screenshot the card containing a canvas, expanded to include the title.

    Args:
        page: The Playwright page.
        canvas_id: The canvas element ID (without #).
        out_path: Destination path for the screenshot.
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


def _screenshot_charts(page: Page) -> None:
    """Capture clipped screenshots of all four Chart.js visualisation canvases."""
    for canvas_id, filename in _CANVAS_IDS.items():
        _clip_canvas(page, canvas_id, _OUT_DIR / filename)


def _screenshot_diff_panel(page: Page) -> None:
    """Expand the first diff panel and capture it; fall back to full-page."""
    try:
        # Details/summary toggles open on click
        first_summary = page.locator('details summary').first
        first_summary.click(timeout=5000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(_OUT_DIR / '07-diff-panel.png'), full_page=True)
        print(f'  07-diff-panel.png  ({(_OUT_DIR / "07-diff-panel.png").stat().st_size // 1024} KB)')
    except Exception as exc:
        print(f'  WARNING: diff panel click failed ({exc}); using full-page fallback')
        page.screenshot(path=str(_OUT_DIR / '07-diff-panel.png'), full_page=True)
        print(f'  07-diff-panel.png  (full-page, {(_OUT_DIR / "07-diff-panel.png").stat().st_size // 1024} KB)')


def _screenshot_full_report(page: Page) -> None:
    """Capture a full-page overview of the complete report."""
    page.screenshot(path=str(_OUT_DIR / '08-full-report.png'), full_page=True)
    print(f'  08-full-report.png  ({(_OUT_DIR / "08-full-report.png").stat().st_size // 1024} KB)')


def main() -> None:
    """Capture all eight capstone screenshots for the Rich HTML Reports milestone."""
    if not _REPORT_PATH.exists():
        raise FileNotFoundError(f'Demo report not found: {_REPORT_PATH}')

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f'Writing screenshots to {_OUT_DIR}\n')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            device_scale_factor=1,
        )
        page = context.new_page()

        _load_report(page)
        _screenshot_dark_mode(page)
        _screenshot_light_mode(page)
        _screenshot_charts(page)
        _screenshot_diff_panel(page)
        _screenshot_full_report(page)

        context.close()
        browser.close()

    print('\nDone.')


if __name__ == '__main__':
    main()
