#!/usr/bin/env python3
"""Epic D demo: Code Diff Sections screenshots.

Captures five screenshots proving collapsible diffs and syntax highlighting
work end-to-end with real mutation data from pytest-gremlins.

HTML structure (from src/pytest_gremlins/reporting/html.py):
  - <details><summary>Show diff</summary> ... </details> — one per result row
  - <div class="diff-panels"> — side-by-side Mogwai / Gremlin panels
  - <div class="diff-unified"> — unified diff with .diff-add / .diff-remove spans
  - <button class="expand-btn" onclick="expandAllDiffs()"> — expand all
  - <button class="expand-btn" onclick="collapseAllDiffs()"> — collapse all
  - <button class="theme-toggle" onclick="toggleTheme()"> — light/dark toggle
"""

from pathlib import Path
import subprocess
import sys
import time

from playwright.sync_api import Browser, sync_playwright


REPORT_DIR = Path('/tmp/gremlin-demo-epicd/report')  # noqa: S108  # nosec B108
OUT_DIR = Path(__file__).parent.parent / 'docs' / 'demo' / 'epic-d-diffs'
HTTP_PORT = 8765


def _start_server() -> subprocess.Popen:  # type: ignore[type-arg]
    """Start a local HTTP server to serve the report (avoids file:// CSP issues)."""
    server = subprocess.Popen(  # nosec B603
        [sys.executable, '-m', 'http.server', str(HTTP_PORT), '--directory', str(REPORT_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    return server


def _shoot_dark_theme(browser: Browser, report_url: str) -> None:
    """Capture screenshots 01-04: collapsed, one expanded, expand-all, collapse-all (dark theme)."""
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = ctx.new_page()
    page.goto(report_url)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)

    # 01: Default state — all diffs collapsed
    page.locator('.expand-controls').scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT_DIR / '01-collapsed.png'), full_page=False)

    # 02: First diff expanded — shows Mogwai/Gremlin panels
    first_summary = page.locator('details summary').first
    first_summary.click()
    page.wait_for_timeout(600)
    first_summary.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT_DIR / '02-expanded.png'), full_page=False)

    # 03: Expand all diffs
    page.locator('button.expand-btn', has_text='Expand all diffs').click()
    page.wait_for_timeout(800)
    page.locator('.expand-controls').scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT_DIR / '03-expand-all.png'), full_page=False)

    # 04: Collapse all diffs
    page.locator('button.expand-btn', has_text='Collapse all diffs').click()
    page.wait_for_timeout(600)
    page.locator('.expand-controls').scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT_DIR / '04-collapse-all.png'), full_page=False)

    ctx.close()


def _shoot_light_theme(browser: Browser, report_url: str) -> None:
    """Capture screenshot 05: light theme with first diff expanded."""
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = ctx.new_page()
    page.goto(report_url)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)

    page.locator('button.theme-toggle').click()
    page.wait_for_timeout(500)

    page.locator('details summary').first.click()
    page.wait_for_timeout(600)

    page.locator('.expand-controls').scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT_DIR / '05-light-theme-diff.png'), full_page=False)

    ctx.close()


def main() -> None:
    """Generate all five Epic-D demo screenshots and print a summary."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_url = f'http://localhost:{HTTP_PORT}/index.html'

    server = _start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            _shoot_dark_theme(browser, report_url)
            _shoot_light_theme(browser, report_url)
            browser.close()
    finally:
        server.terminate()

    print(f'Screenshots saved to {OUT_DIR}/')
    for f in sorted(OUT_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f'  {f.name}  ({size_kb} KB)')


if __name__ == '__main__':
    main()
