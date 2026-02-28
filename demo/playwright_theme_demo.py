"""Playwright screenshot demos for Epic B: Visual Redesign & Dark/Light Mode.

Captures four screenshots of the pytest-gremlins HTML report:
  01-dark-mode.png       - Default dark theme
  02-light-mode.png      - After toggling to light theme
  03-light-persists.png  - Light theme persisted after page reload
  04-mobile.png          - Mobile viewport (375x812) with no horizontal overflow
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright


_REPORT_PATH = Path('/tmp/gremlin-demo-epicb/report/index.html')  # noqa: S108  # nosec B108
_OUTPUT_DIR = Path(__file__).parent.parent / 'docs' / 'demo' / 'epic-b-theme'


def _take_dark_mode_screenshot(page: Page) -> None:
    """Navigate to the report and capture the default dark-mode screenshot."""
    report_url = _REPORT_PATH.resolve().as_uri()
    page.goto(report_url)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_OUTPUT_DIR / '01-dark-mode.png'), full_page=True)


def _take_light_mode_screenshot(page: Page) -> None:
    """Click the theme toggle and capture the light-mode screenshot."""
    page.click('button.theme-toggle')
    page.wait_for_timeout(500)
    page.screenshot(path=str(_OUTPUT_DIR / '02-light-mode.png'), full_page=True)


def _take_light_persists_screenshot(page: Page) -> None:
    """Reload the page and verify light mode persists via localStorage."""
    page.reload()
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    page.screenshot(path=str(_OUTPUT_DIR / '03-light-persists.png'), full_page=True)


def _take_mobile_screenshot(page: Page) -> None:
    """Set a 375x812 mobile viewport and capture with no horizontal overflow."""
    page.set_viewport_size({'width': 375, 'height': 812})
    page.screenshot(path=str(_OUTPUT_DIR / '04-mobile.png'), full_page=True)


def run_demo() -> None:
    """Run all four Playwright screenshot captures for the Epic B theme demo."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            device_scale_factor=2,
        )
        page = context.new_page()

        _take_dark_mode_screenshot(page)
        _take_light_mode_screenshot(page)
        _take_light_persists_screenshot(page)
        _take_mobile_screenshot(page)

        context.close()
        browser.close()

    print('Screenshots written to:', _OUTPUT_DIR.resolve())


if __name__ == '__main__':
    run_demo()
