"""Metric snapshot history persistence for Janus.

Append-only store of metric values over time, kept in ``data/metric_history.md``
for consistency with the rest of the Janus persistence layer (all files are
markdown).  The line-based format keeps it simple and human-readable.

Format::

    # Metric History
    # Format: ISO-timestamp | goal_title | metric_name | value | source
    2026-09-06T10:00:00+02:00 | Body fat % | 20.0 | manual
    2026-09-13T10:00:00+02:00 | Body fat % | 19.5 | manual

Snapshots are NEVER modified or deleted by the system — the file is append-only.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import logging

from janus._log import emit

PROJECT_ROOT = Path(__file__).resolve().parents[3]
METRIC_HISTORY_PATH = PROJECT_ROOT / "data" / "metric_history.md"

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """A single metric value snapshot recorded at a point in time.

    ``timestamp`` carries timezone information (ISO 8601 with offset) so that
    the snapshot is unambiguous regardless of the host timezone.
    """

    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # manual | measurement | import


def load_snapshots(path: Path | None = None) -> list[MetricSnapshot]:
    """Load all metric snapshots from the history file.

    Returns an empty list if the file is missing.  Malformed lines are
    skipped with a warning, so a single bad entry never corrupts the whole
    history.
    """
    log_path = path if path is not None else METRIC_HISTORY_PATH
    if not log_path.exists():
        return []

    snapshots: list[MetricSnapshot] = []
    with log_path.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            snapshot = _parse_snapshot_line(line, line_num)
            if snapshot is not None:
                snapshots.append(snapshot)
    return snapshots


def get_metric_snapshots(
    goal_title: str,
    since: datetime | None = None,
    until: datetime | None = None,
    path: Path | None = None,
) -> list[MetricSnapshot]:
    """Return snapshots for ``goal_title`` within ``[since, until`` (inclusive).

    ``since`` and ``until`` are inclusive on both ends.  If omitted, no
    lower/upper bound is applied.  Results are sorted by timestamp ascending.

    The function accepts either datetimes (preferred for precise comparison)
    or dates (compared by midnight).  Dates are accepted for ergonomics.
    """
    from datetime import date as _date
    from datetime import timezone as _tz

    snapshots = load_snapshots(path)
    result = [s for s in snapshots if s.goal_title == goal_title]

    if since is not None:
        if isinstance(since, _date) and not isinstance(since, datetime):
            since = datetime.combine(since, datetime.min.time(), tzinfo=_tz.utc)
        result = [s for s in result if s.timestamp >= since]

    if until is not None:
        if isinstance(until, _date) and not isinstance(until, datetime):
            until = datetime.combine(until, datetime.max.time(), tzinfo=_tz.utc)
        result = [s for s in result if s.timestamp <= until]

    result.sort(key=lambda s: s.timestamp)
    return result


def append_snapshot(
    snapshot: MetricSnapshot,
    path: Path | None = None,
) -> None:
    """Append a single snapshot to the history file.

    Creates the file (with header comment) if it doesn't exist.  Parent
    directories are created as needed.  The write is append-only — existing
    entries are never touched.
    """
    log_path = path if path is not None else METRIC_HISTORY_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = (
        f"{snapshot.timestamp.isoformat()} | "
        f"{snapshot.goal_title} | "
        f"{snapshot.metric_name} | "
        f"{snapshot.value} | "
        f"{snapshot.source}"
    )

    header = (
        "# Metric History\n"
        "# Format: ISO-timestamp | goal_title | metric_name | value | source\n"
    )

    write_header = not log_path.exists() or log_path.stat().st_size == 0

    with log_path.open("a") as f:
        if write_header:
            f.write(header)
        f.write(line + "\n")

    emit(logger, "metric_history.snapshot.appended",
         trace_id=None, span_id="metric_history",
         goal_title=snapshot.goal_title,
         metric_name=snapshot.metric_name,
         value=snapshot.value,
         source=snapshot.source,
         file_path=str(log_path),
         message=f"Metric snapshot appended for '{snapshot.goal_title}'")


def _parse_snapshot_line(line: str, line_num: int) -> MetricSnapshot | None:
    """Parse a single snapshot line into a MetricSnapshot.

    Returns None (with a warning) if the line is malformed.
    """
    parts = line.split(" | ")
    if len(parts) != 5:
        logger.warning(
            f"Skipping malformed metric history line {line_num}: "
            f"expected 5 fields, got {len(parts)}"
        )
        return None

    ts_str, goal_title, metric_name, value_str, source = [
        p.strip() for p in parts
    ]

    try:
        timestamp = datetime.fromisoformat(ts_str)
    except ValueError:
        logger.warning(
            f"Skipping malformed metric history line {line_num}: "
            f"invalid timestamp '{ts_str}'"
        )
        return None

    try:
        value = float(value_str)
    except ValueError:
        logger.warning(
            f"Skipping malformed metric history line {line_num}: "
            f"invalid value '{value_str}'"
        )
        return None

    if not goal_title or not metric_name:
        logger.warning(
            f"Skipping malformed metric history line {line_num}: "
            f"empty goal_title or metric_name"
        )
        return None

    return MetricSnapshot(
        timestamp=timestamp,
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )
