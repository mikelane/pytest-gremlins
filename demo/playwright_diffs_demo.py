r"""Playwright video demo for Epic D: Code Diff Sections.

Records a narration-synced video demonstrating:
  - Default collapsed diff state
  - Expanding a single diff inline (Mogwai / Gremlin panels)
  - Expand all diffs at once
  - Collapse all diffs
  - Light theme with diffs still readable

Run from the demo/ directory:
    uv run python playwright_diffs_demo.py

Output: /tmp/epic-d-demo/<timestamp>.webm
Combine with narration:
    ffmpeg -y \
        -i <video.webm> \
        -i demo/narration/epic-d-narration.mp3 \
        -c:v libx264 -pix_fmt yuv420p -r 30 \
        -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
        -c:a aac -b:a 128k -shortest \
        docs/demo/epic-d-diffs.mp4
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

_TIMING_PATH = Path(__file__).parent / 'narration' / 'epic-d-timing.json'
_REPORT_DIR = Path('/tmp/gremlin-demo-epicd/report')  # noqa: S108  # nosec B108
_VIDEO_DIR = Path('/tmp/epic-d-demo')  # noqa: S108  # nosec B108
_HTTP_PORT = 8765


def _ms(timings: list[dict], name: str) -> int:
    """Return segment duration in milliseconds."""
    seg = next(t for t in timings if t['name'] == name)
    return round(seg['duration'] * 1000)


def _start_server() -> subprocess.Popen:  # type: ignore[type-arg]
    """Start a local HTTP server to serve the report (avoids file:// CSP issues)."""
    server = subprocess.Popen(  # nosec B603
        [sys.executable, '-m', 'http.server', str(_HTTP_PORT), '--directory', str(_REPORT_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    return server


def run_demo() -> None:
    """Record narration-synced video of the Epic D diff sections demo."""
    timings = json.loads(_TIMING_PATH.read_text())
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    report_url = f'http://localhost:{_HTTP_PORT}/index.html'
    server = _start_server()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(
                viewport={'width': 1280, 'height': 900},
                device_scale_factor=2,
                record_video_dir=str(_VIDEO_DIR),
                record_video_size={'width': 1280, 'height': 900},
            )
            page = context.new_page()

            # -- intro (9.85s): navigate to report, show default dark theme --
            page.goto(report_url)
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(_ms(timings, 'intro'))

            # -- collapsed (8.08s): scroll to expand-controls, show collapsed default state --
            page.locator('.expand-controls').scroll_into_view_if_needed()
            page.wait_for_timeout(_ms(timings, 'collapsed'))

            # -- expand_one (8.41s): click first diff summary, Mogwai/Gremlin panels appear --
            page.locator('details summary').first.click()
            page.wait_for_timeout(600)
            page.locator('details summary').first.scroll_into_view_if_needed()
            page.wait_for_timeout(_ms(timings, 'expand_one') - 600)

            # -- expand_all (5.20s): click Expand all diffs --
            page.locator('button.expand-btn', has_text='Expand all diffs').click()
            page.wait_for_timeout(500)
            page.locator('.expand-controls').scroll_into_view_if_needed()
            page.wait_for_timeout(_ms(timings, 'expand_all') - 500)

            # -- collapse_all (5.39s): click Collapse all diffs --
            page.locator('button.expand-btn', has_text='Collapse all diffs').click()
            page.wait_for_timeout(400)
            page.locator('.expand-controls').scroll_into_view_if_needed()
            page.wait_for_timeout(_ms(timings, 'collapse_all') - 400)

            # -- light_theme (6.08s): toggle to light mode, show diffs still readable --
            page.locator('button.theme-toggle').click()
            page.wait_for_timeout(500)
            page.locator('details summary').first.click()
            page.wait_for_timeout(400)
            page.locator('.expand-controls').scroll_into_view_if_needed()
            page.wait_for_timeout(_ms(timings, 'light_theme') - 900)

            # -- outro (11.66s + 4s buffer): hold final state, video outlasts narration --
            page.wait_for_timeout(_ms(timings, 'outro') + 4000)

            video_path = page.video.path()
            context.close()
            browser.close()
    finally:
        server.terminate()

    print(f'Video: {video_path}')


if __name__ == '__main__':
    run_demo()
