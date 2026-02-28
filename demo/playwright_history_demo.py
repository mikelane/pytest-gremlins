"""Playwright screenshot demo for Epic E: Historical Trend Tracking.

Opens the mutation testing HTML report and captures screenshots of the
history trend chart, score gauge, and full report for documentation.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright


_REPORT_PATH = Path('/tmp/gremlin-demo-epice/report/index.html')  # noqa: S108  # nosec B108
_OUTPUT_DIR = Path(__file__).parent.parent / 'docs' / 'demo' / 'epic-e-history'
_WAIT_MS = 4000


def _screenshot_history_section(page: Page) -> None:
    """Screenshot the history trend chart section to a PNG file.

    Locates the #historySection element and captures its bounding box.
    Falls back to a full-page screenshot if the element is not found.

    Args:
        page: The Playwright page object.
    """
    output_path = _OUTPUT_DIR / '01-trend-chart.png'
    history_locator = page.locator('#historySection')
    if history_locator.count() > 0:
        history_locator.screenshot(path=str(output_path))
        print(f'Screenshot saved: {output_path}')
    else:
        page.screenshot(path=str(output_path), full_page=True)
        print(f'historySection not found - full-page fallback: {output_path}')


def _screenshot_score_gauge(page: Page) -> None:
    """Screenshot the score gauge element to a PNG file.

    Tries common gauge selectors before falling back to a full-page capture.

    Args:
        page: The Playwright page object.
    """
    output_path = _OUTPUT_DIR / '02-score-gauge.png'
    for selector in ('.score-gauge', '.gauge', '.summary', '.score-card', 'header'):
        gauge_locator = page.locator(selector)
        if gauge_locator.count() > 0:
            gauge_locator.first.screenshot(path=str(output_path))
            print(f'Score gauge screenshot saved ({selector}): {output_path}')
            return
    page.screenshot(path=str(output_path), full_page=False)
    print(f'Gauge selector not found - viewport fallback: {output_path}')


def _screenshot_full_report(page: Page) -> None:
    """Screenshot the entire report page to a PNG file.

    Args:
        page: The Playwright page object.
    """
    output_path = _OUTPUT_DIR / '03-full-report.png'
    page.screenshot(path=str(output_path), full_page=True)
    print(f'Full report screenshot saved: {output_path}')


def run_demo() -> None:
    """Open the mutation report and capture Epic-E history screenshots.

    Launches a headless Chromium browser, navigates to the local HTML report,
    waits for Chart.js to render, then captures three screenshots.
    """
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report_url = _REPORT_PATH.as_uri()
    print(f'Opening report: {report_url}')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})

        page.goto(report_url, wait_until='load')
        page.wait_for_timeout(_WAIT_MS)

        _screenshot_history_section(page)
        _screenshot_score_gauge(page)
        _screenshot_full_report(page)

        browser.close()

    print('Demo screenshots complete.')


if __name__ == '__main__':
    run_demo()
