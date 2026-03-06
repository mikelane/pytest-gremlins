"""History management for gremlin mutation testing reports.

Provides functions for persisting per-run mutation scores to a JSON history
file so that trend charts can be rendered across multiple runs.
"""

from __future__ import annotations

from datetime import (
    UTC,
    datetime,
)
import json
import logging
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from pytest_gremlins.reporting.score import MutationScore

logger = logging.getLogger(__name__)


def _build_operator_data(score: MutationScore) -> dict[str, dict[str, int]]:
    """Aggregate per-operator totals and survivor counts from a MutationScore.

    Args:
        score: The MutationScore whose results are aggregated.

    Returns:
        Mapping of operator name to ``{'total': int, 'survived': int}``.
    """
    op_data: dict[str, dict[str, int]] = {}
    for result in score.results:
        op = result.gremlin.operator_name
        if op not in op_data:
            op_data[op] = {'total': 0, 'survived': 0}
        op_data[op]['total'] += 1
        if result.status == GremlinResultStatus.SURVIVED:
            op_data[op]['survived'] += 1
    return op_data


def append_history_entry(
    rootdir: Path,
    score: MutationScore,
    history_limit: int = 30,
    history_path: Path | None = None,
) -> Path:
    """Append a history entry to the JSON history file and enforce the cap.

    The history file lives at ``<rootdir>/coverage/gremlins/history.json``
    unless overridden by *history_path*.

    Each entry has the shape::

        {
            "timestamp": "<ISO8601>",
            "score": <float>,
            "by_file": {"<path>": <score_float>, ...},
            "by_operator": {"<op>": {"total": <int>, "survived": <int>}, ...}
        }

    Args:
        rootdir: Project root directory (anchor for default history path).
        score: The MutationScore to record.
        history_limit: Maximum number of history entries to retain (oldest dropped).
        history_path: Override the default history file path.

    Returns:
        Path to the history JSON file.
    """
    path = history_path or (rootdir / 'coverage' / 'gremlins' / 'history.json')
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            logger.warning('Could not read existing history from %s, starting fresh', path, exc_info=True)
            existing = []

    by_file = {fp: round(fs.percentage, 2) for fp, fs in score.by_file().items()}

    entry = {
        'timestamp': datetime.now(UTC).isoformat(),
        'score': round(score.percentage, 2),
        'by_file': by_file,
        'by_operator': _build_operator_data(score),
    }

    existing.append(entry)
    if len(existing) > history_limit:
        existing = existing[-history_limit:]

    path.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    return path


def load_history(history_path: Path) -> list[dict[str, Any]]:
    """Load history entries from the JSON file.

    Args:
        history_path: Path to the history JSON file.

    Returns:
        List of history entry dicts, or empty list if file is absent/corrupt.
    """
    if not history_path.exists():
        return []
    try:
        result: list[dict[str, Any]] = json.loads(history_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        logger.warning('Could not load history from %s', history_path, exc_info=True)
        return []
    else:
        return result
