"""Playwright recording script for Epic C — Chart.js Visualizations demo.

Records a narrated walkthrough of the pytest-gremlins HTML report charts at 1920x1080.
Audio timing is driven by demo/timing.json so video and narration stay in sync.

Run from the worktree root:
    uv run python demo/playwright_charts_demo.py
"""

from __future__ import annotations

import json
import pathlib

from playwright.sync_api import Page, sync_playwright


TIMING_FILE = pathlib.Path(__file__).parent / 'timing.json'
NORMAL_REPORT = 'file:///tmp/gremlin-demo-epicc/report-normal/index.html'  # nosec B108
PERFECT_REPORT = 'file:///tmp/perfect/report-perfect/index.html'  # nosec B108
VIDEO_OUT_DIR = '/tmp/epic-c-video'  # noqa: S108  # nosec B108
VIEWPORT = {'width': 1920, 'height': 1080}


def ms(seconds: float) -> int:
    """Convert seconds to milliseconds, rounded to the nearest integer."""
    return round(seconds * 1000)


def load_timing() -> dict[str, float]:
    """Load segment durations from timing.json keyed by segment name."""
    segments = json.loads(TIMING_FILE.read_text())
    return {seg['name']: seg['duration'] for seg in segments}


def scroll_to(page: Page, selector: str) -> None:
    """Scroll the element matching selector into view if it exists."""
    try:
        page.locator(selector).first.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        page.evaluate(f"document.querySelector('{selector}')?.scrollIntoView({{behavior: 'smooth', block: 'center'}})")


def record_demo() -> None:
    """Record the full Epic C demo video with chart walkthroughs."""
    timing = load_timing()

    pathlib.Path(VIDEO_OUT_DIR).mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=VIDEO_OUT_DIR,
            record_video_size=VIEWPORT,
        )
        page = context.new_page()
        page.set_default_timeout(120_000)

        # Segment 1: intro — normal report landing page
        page.goto(NORMAL_REPORT, wait_until='networkidle')
        page.wait_for_timeout(ms(timing['intro']))

        # Segment 2: score_gauge
        scroll_to(page, '#scoreGauge')
        page.wait_for_timeout(ms(timing['score_gauge']))

        # Segment 3: outcome_pie
        scroll_to(page, '#outcomeChart')
        page.wait_for_timeout(ms(timing['outcome_pie']))

        # Segment 4: file_bar
        scroll_to(page, '#fileChart')
        page.wait_for_timeout(ms(timing['file_bar']))

        # Segment 5: operator_chart
        scroll_to(page, '#operatorChart')
        page.wait_for_timeout(ms(timing['operator_chart']))

        # Segment 6: perfect_score — navigate to perfect report
        page.goto(PERFECT_REPORT, wait_until='networkidle')
        page.wait_for_timeout(ms(timing['perfect_score']))

        # Segment 7: outro — stay on perfect report, 3s extra buffer
        page.wait_for_timeout(ms(timing['outro']) + 3000)

        context.close()
        browser.close()

    video_files = sorted(pathlib.Path(VIDEO_OUT_DIR).glob('*.webm'))
    if video_files:
        print(video_files[-1])
    else:
        print(f'No .webm found in {VIDEO_OUT_DIR}')


if __name__ == '__main__':
    record_demo()
