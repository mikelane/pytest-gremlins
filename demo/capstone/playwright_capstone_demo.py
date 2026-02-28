#!/usr/bin/env python3
r"""Epic F capstone demo: narration-synced video of the full Rich HTML Reports milestone.

Covers all five epics in one walkthrough:
  - intro:          the finished report as a whole
  - run:            the terminal command that produces it
  - dark_mode:      default dark theme on load
  - light_toggle:   one-click theme switch via CSS custom properties
  - score_gauge:    mutation score gauge
  - outcome_pie:    zapped/survived/timeout breakdown
  - file_bar:       per-file mutation scores
  - operator_chart: surviving mutations by operator type
  - diff_expand:    mogwai vs gremlin unified diff
  - history:        score trend across four runs
  - outro:          the complete single-file artifact

Run from the worktree root:
    uv run python demo/capstone/playwright_capstone_demo.py

Output: /tmp/epic-f-demo/<timestamp>.webm
Combine with narration:
    ffmpeg -y \\
        -i <video.webm> \\
        -i demo/capstone/epic-f-narration.mp3 \\
        -c:v libx264 -pix_fmt yuv420p -r 30 \\
        -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \\
        -c:a aac -b:a 128k -shortest \\
        docs/demo/rich-html-reports-demo.mp4
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


_TIMING_PATH = Path(__file__).parent / 'timing.json'
_REPORT_PATH = Path('/tmp/gremlin-demo-epicf/report/index.html')  # noqa: S108  # nosec B108
_RUN_PATH = Path('/tmp/gremlin-demo-epicf/run.html')  # noqa: S108  # nosec B108
_VIDEO_DIR = Path('/tmp/epic-f-demo')  # noqa: S108  # nosec B108

_CHART_RENDER_MS = 4000


def _ms(timings: list[dict], name: str) -> int:
    """Return segment duration in milliseconds."""
    seg = next(t for t in timings if t['name'] == name)
    return round(seg['duration'] * 1000)


def _load_report(page: Page) -> None:
    """Navigate to the report and wait for Chart.js to finish rendering."""
    page.goto(_REPORT_PATH.resolve().as_uri())
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(_CHART_RENDER_MS)


def run_demo() -> None:
    """Record narration-synced video of the Epic F capstone demo."""
    timings = json.loads(_TIMING_PATH.read_text())
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            device_scale_factor=2,
            record_video_dir=str(_VIDEO_DIR),
            record_video_size={'width': 1280, 'height': 900},
        )
        page = context.new_page()

        # -- intro (12957ms): show the finished report, charts already rendered --
        _load_report(page)
        page.evaluate('window.scrollTo(0, 0)')
        # Scroll down gently to show the report has content, then back
        page.wait_for_timeout(3000)
        page.evaluate('window.scrollTo(0, 500)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(_ms(timings, 'intro') - _CHART_RENDER_MS - 3000 - 2000 - 500)

        # -- run (14629ms): show the terminal command that produced the report --
        page.goto(_RUN_PATH.resolve().as_uri())
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(_ms(timings, 'run') - 500)

        # -- dark_mode (12307ms): back to report, chart render counts here --
        _load_report(page)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(_ms(timings, 'dark_mode') - _CHART_RENDER_MS - 500)

        # -- light_toggle (11006ms): one click, whole report re-renders --
        page.click('button.theme-toggle')
        page.wait_for_timeout(600)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(5000)
        page.click('button.theme-toggle')
        page.wait_for_timeout(600)
        page.wait_for_timeout(_ms(timings, 'light_toggle') - 600 - 5000 - 600 - 500)

        # -- score_gauge (9985ms): scroll the gauge into view --
        page.locator('#scoreGauge').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'score_gauge') - 500)

        # -- outcome_pie (11192ms): scroll to outcome pie --
        page.locator('#outcomeChart').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'outcome_pie') - 500)

        # -- file_bar (12725ms): scroll to per-file bar chart --
        page.locator('#fileChart').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'file_bar') - 500)

        # -- operator_chart (15232ms): scroll to operator breakdown --
        page.locator('#operatorChart').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'operator_chart') - 500)

        # -- diff_expand (16022ms): scroll to diffs, expand the first row --
        page.locator('details').first.scroll_into_view_if_needed()
        page.wait_for_timeout(1500)
        page.locator('details summary').first.click()
        page.wait_for_timeout(600)
        page.wait_for_timeout(_ms(timings, 'diff_expand') - 1500 - 600 - 500)

        # -- history (11610ms): scroll to history trend section --
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'history') - 500)

        # -- outro (12028ms + 4000ms buffer): hold on history, video outlasts audio --
        page.wait_for_timeout(_ms(timings, 'outro') + 4000)

        video_path = page.video.path()
        context.close()
        browser.close()

    print(f'Video: {video_path}')


if __name__ == '__main__':
    run_demo()
