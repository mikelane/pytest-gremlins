#!/usr/bin/env python3
"""Classify a release tag: is it a PEP 440 pre-release (``aN``, ``bN``, ``rcN``, ``cN`` or ``.devN``)?

The release workflow runs this before creating the GitHub Release and passes the result to
``prerelease:``. The tag is parsed, not substring-matched, so ``v1.9.0b3`` is a pre-release and
a final tag is never one. Under GitHub Actions the decision is appended to ``$GITHUB_OUTPUT``;
otherwise it is printed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

# ``uv run --no-project`` has no ``packaging``, so the pre-release rule is spelled out. It covers every tag that
# ``verify_release_tag.py`` accepts and PEP 440 treats as a pre-release: a pre-release segment, a dev segment, or both.
PRERELEASE_TAG_PATTERN = re.compile(
    r'v[0-9]+\.[0-9]+\.[0-9]+'
    r'(?:(?:alpha|beta|preview|pre|rc|a|b|c)[0-9]*(?:\.post[0-9]+)?(?:\.dev[0-9]+)?'
    r'|(?:\.post[0-9]+)?\.dev[0-9]+)'
)


def is_prerelease(tag: str) -> bool:
    """Return True when the tag is ``vMAJOR.MINOR.PATCH`` followed by a PEP 440 pre-release or dev segment."""
    return PRERELEASE_TAG_PATTERN.fullmatch(tag) is not None


def main() -> int:
    """Print or export ``prerelease=true|false`` for the tag given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    args = parser.parse_args()
    line = f'prerelease={str(is_prerelease(args.tag)).lower()}'
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with Path(github_output).open('a') as output:
            output.write(f'{line}\n')
    else:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
