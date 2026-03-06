r"""Playwright video demo for Epic B: Visual Redesign & Dark/Light Mode.

Records a narration-synced video demonstrating:
  - Default dark theme
  - One-click theme toggle (dark to light)
  - Light theme persistence across reloads (localStorage)
  - Responsive mobile layout at 375px

Run from the demo/ directory:
    uv run python playwright_theme_demo.py

Output: /tmp/epic-b-demo/<timestamp>.webm
Combine with narration:
    ffmpeg -y \\
        -i <video.webm> \\
        -i /tmp/epic-b-narration/epic-b-narration.mp3 \\
        -c:v libx264 -pix_fmt yuv420p -r 30 \\
        -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \\
        -c:a aac -b:a 128k -shortest \\
        epic-b-theme.mp4
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

_TIMING_PATH = Path(__file__).parent / 'narration' / 'epic-b-timing.json'
_REPORT_PATH = Path('/tmp/gremlin-demo-epicb/report/index.html')  # noqa: S108  # nosec B108
_VIDEO_DIR = Path('/tmp/epic-b-demo')  # noqa: S108  # nosec B108


def _ms(timings: list[dict], name: str) -> int:
    """Return segment duration in milliseconds."""
    seg = next(t for t in timings if t['name'] == name)
    return round(seg['duration'] * 1000)


def run_demo() -> None:
    """Record narration-synced video of the Epic B theme demo."""
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

        # -- intro (10.2s): navigate to report, dark mode loads immediately --
        page.goto(_REPORT_PATH.resolve().as_uri())
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(_ms(timings, 'intro'))

        # -- dark_mode (8.6s): hold on dark-themed report --
        page.wait_for_timeout(_ms(timings, 'dark_mode'))

        # -- toggle (4.1s): click theme toggle, show light mode --
        page.click('button.theme-toggle')
        page.wait_for_timeout(_ms(timings, 'toggle'))

        # -- persist (6.1s): reload, light theme still active via localStorage --
        page.reload()
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(_ms(timings, 'persist'))

        # -- mobile (7.6s): resize to 375px, show responsive layout --
        page.set_viewport_size({'width': 375, 'height': 812})
        page.wait_for_timeout(_ms(timings, 'mobile'))

        # -- outro (11.9s + 4s buffer): hold final state, video outlasts narration --
        page.wait_for_timeout(_ms(timings, 'outro') + 4000)

        video_path = page.video.path()
        context.close()
        browser.close()

    print(f'Video: {video_path}')


if __name__ == '__main__':
    run_demo()
