r"""Playwright video demo for Epic E: Historical Trend Tracking.

Records a narration-synced video demonstrating:
  - Single baseline data point after run 1
  - Trend line growing to 2, then 3 stable data points
  - History section with full 3-run trend visible
  - Regression dip on run 4 after a test is removed

The history data is injected programmatically between page reloads so
the chart renders with 1, 2, 3, then 4 entries without re-running pytest.

Run from the demo/ directory:
    uv run python playwright_history_demo.py

Output: /tmp/epic-e-demo/<timestamp>.webm
Combine with narration:
    ffmpeg -y \
        -i <video.webm> \
        -i demo/narration/epic-e-narration.mp3 \
        -c:v libx264 -pix_fmt yuv420p -r 30 \
        -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
        -c:a aac -b:a 128k -shortest \
        /tmp/epic-e-demo/epic-e-history.mp4
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from playwright.sync_api import Page, sync_playwright


_TIMING_PATH = Path(__file__).parent / 'narration' / 'epic-e-timing.json'
_REPORT_PATH = Path('/tmp/gremlin-demo-epice/report/index.html')  # noqa: S108  # nosec B108
_VIDEO_DIR = Path('/tmp/epic-e-demo')  # noqa: S108  # nosec B108
_DEMO_CALC_PATH = '/tmp/gremlin-demo-epice/calculator.py'  # noqa: S108  # nosec B108

# All 4 history entries: 3 stable, 1 regression
_ALL_HISTORY = [
    {
        'timestamp': '2026-02-27T23:27:28.973733+00:00',
        'score': 63.64,
        'by_file': {_DEMO_CALC_PATH: 63.64},
        'by_operator': {
            'arithmetic': {'total': 4, 'survived': 1},
            'comparison': {'total': 2, 'survived': 1},
            'boundary': {'total': 3, 'survived': 1},
            'return_value': {'total': 2, 'survived': 0},
        },
    },
    {
        'timestamp': '2026-02-28T00:27:28.973947+00:00',
        'score': 63.64,
        'by_file': {_DEMO_CALC_PATH: 63.64},
        'by_operator': {
            'arithmetic': {'total': 4, 'survived': 1},
            'comparison': {'total': 2, 'survived': 1},
            'boundary': {'total': 3, 'survived': 1},
            'return_value': {'total': 2, 'survived': 0},
        },
    },
    {
        'timestamp': '2026-02-28T01:27:28.973968+00:00',
        'score': 63.64,
        'by_file': {_DEMO_CALC_PATH: 63.64},
        'by_operator': {
            'arithmetic': {'total': 4, 'survived': 1},
            'comparison': {'total': 2, 'survived': 1},
            'boundary': {'total': 3, 'survived': 1},
            'return_value': {'total': 2, 'survived': 0},
        },
    },
    {
        'timestamp': '2026-02-28T02:27:28.973968+00:00',
        'score': 45.45,
        'by_file': {_DEMO_CALC_PATH: 45.45},
        'by_operator': {
            'arithmetic': {'total': 4, 'survived': 3},
            'comparison': {'total': 2, 'survived': 1},
            'boundary': {'total': 3, 'survived': 2},
            'return_value': {'total': 2, 'survived': 0},
        },
    },
]


def _ms(timings: list[dict], name: str) -> int:
    """Return segment duration in milliseconds."""
    seg = next(t for t in timings if t['name'] == name)
    return round(seg['duration'] * 1000)


def _set_history(page: Page, entries: list[dict]) -> None:
    """Inject history entries into the historyChart canvas data-history attribute.

    Writes the JSON directly to disk and reloads so Chart.js picks up
    the new data-history value on the freshly rendered canvas element.

    Args:
        page: The Playwright page object.
        entries: History entries to embed (1, 2, 3, or 4 items).
    """
    encoded = json.dumps(entries, separators=(',', ':')).replace('"', '&quot;')
    html_path = _REPORT_PATH
    html = html_path.read_text()
    patched = re.sub(
        r'(<canvas id="historyChart"[^>]*data-history=")[^"]*(")',
        rf'\g<1>{encoded}\g<2>',
        html,
    )
    html_path.write_text(patched)
    page.reload()
    page.wait_for_load_state('networkidle')


def run_demo() -> None:
    """Record narration-synced video of the Epic E history trend demo."""
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

        # -- intro (8.5s): load report with 1 history entry, chart shows baseline --
        _set_history(page, _ALL_HISTORY[:1])
        page.goto(_REPORT_PATH.resolve().as_uri())
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(_ms(timings, 'intro'))

        # -- first_run (4.3s): scroll to history section, 1 point visible --
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'first_run'))

        # -- second_run (5.4s): inject 2 entries, reload, show 2-point chart --
        _set_history(page, _ALL_HISTORY[:2])
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'second_run'))

        # -- third_run (5.7s): inject 3 entries, reload, show 3-point chart --
        _set_history(page, _ALL_HISTORY[:3])
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'third_run'))

        # -- trend_chart (8.7s): scroll to top, back to history for full view --
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(1500)
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'trend_chart') - 1500)

        # -- regression (7.7s): inject all 4 entries, reload, show dip on run 4 --
        _set_history(page, _ALL_HISTORY)
        page.locator('#historySection').scroll_into_view_if_needed()
        page.wait_for_timeout(_ms(timings, 'regression'))

        # -- outro (8.7s + 4s buffer): hold final state, video outlasts narration --
        page.wait_for_timeout(_ms(timings, 'outro') + 4000)

        video_path = page.video.path()
        context.close()
        browser.close()

    print(f'Video: {video_path}')


if __name__ == '__main__':
    run_demo()
