"""Append-only metric snapshot history for Janus goals.

Reads and writes ``data/metric_history.md`` in a simple comment-line format.
The file is a human-readable, append-only log of metric values recorded for
goals over time. It is consumed by the goal-health service to compute progress
trends, inactivity, and measurement-due signals.
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
METRIC_HISTORY_PATH = PROJECT_ROOT / "data" / "metric_history.md"

logger = logging.getLogger(__name__)

# Field order for the comment-line format.
# Format: # <timestamp> | <goal_title> | <metric_name> | <value> | <source>
_HEADER_LINES = [
    "# Metric History",
    "# Format: ISO-timestamp | goal_title | metric_name | value | source",
]


@dataclass
class MetricSnapshot:
    """A single metric value recorded for a goal at a point in time."""

    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # manual | measurement | import


def _parse_line(line: str) -> MetricSnapshot | None:
    """Parse a single metric history comment line into a MetricSnapshot.

    Returns None for blank or non-data lines (headers, comments without
    the 5-field pipe format).
    """
    stripped = line.strip()
    if not stripped or not stripped.startswith("#"):
        return None
    # Remove the leading "#"
    content = stripped[1:].strip()
    parts = [p.strip() for p in content.split("|")]
    if len(parts) != 5:
        return None
    try:
        ts = datetime.fromisoformat(parts[0])
    except ValueError:
        return None
    try:
        val = float(parts[3])
    except ValueError:
        return None
    return MetricSnapshot(
        timestamp=ts,
        goal_title=parts[1],
        metric_name=parts[2],
        value=val,
        source=parts[4],
    )


def get_metric_snapshots(
    goal_title: str,
    since: datetime | None = None,
    until: datetime | None = None,
    path: Path | None = None,
) -> list[MetricSnapshot]:
    """Return snapshots for a goal within an optional time range.

    Args:
        goal_title: Goal title to match (identity is the title string).
        since: Inclusive lower bound on timestamp (None = no lower bound).
        until: Inclusive upper bound on timestamp (None = no upper bound).
        path: Override the history file path (used by tests).

    Returns:
        Snapshots sorted ascending by timestamp. Empty list if the file
        does not exist or no snapshots match.
    """
    history_path = path if path is not None else METRIC_HISTORY_PATH
    if not history_path.exists():
        return []

    results: list[MetricSnapshot] = []
    with history_path.open() as f:
        for line in f:
            snap = _parse_line(line)
            if snap is None:
                continue
            if snap.goal_title != goal_title:
                continue
            if since is not None and snap.timestamp < since:
                continue
            if until is not None and snap.timestamp > until:
                continue
            results.append(snap)
    results.sort(key=lambda s: s.timestamp)
    return results


def append_metric_snapshot(
    snapshot: MetricSnapshot,
    path: Path | None = None,
) -> None:
    """Append a single snapshot to the metric history file.

    Creates the file (with header) on first use. Existing entries are never
    modified or deleted — the file is strictly append-only.

    Args:
        snapshot: The MetricSnapshot to record.
        path: Override the history file path (used by tests).
    """
    history_path = path if path is not None else METRIC_HISTORY_PATH
    should_write_header = not history_path.exists()
    history_path.parent.mkdir(parents=True, exist_ok=True)

    line = (
        f"# {snapshot.timestamp.isoformat()} | "
        f"{snapshot.goal_title} | "
        f"{snapshot.metric_name} | "
        f"{snapshot.value} | "
        f"{snapshot.source}"
    )

    with history_path.open("a") as f:
        if should_write_header:
            for h in _HEADER_LINES:
                f.write(h + "\n")
        f.write(line + "\n")

    logger.debug(
        "Appended metric snapshot for goal %s: %s=%.2f (%s)",
        snapshot.goal_title,
        snapshot.metric_name,
        snapshot.value,
        snapshot.source,
    )
