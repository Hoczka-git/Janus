"""Measurement log persistence for Janus.

A read-only interface over data/measurements.jsonl that isolates file format
details from the collection logic. If the storage format changes in the future
(e.g., to SQLite or an API), only this module needs to change.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEASUREMENTS_PATH = PROJECT_ROOT / "data" / "measurements.jsonl"

logger = logging.getLogger(__name__)


@dataclass
class MeasurementEntry:
    """A single measurement recorded for a goal + metric pair."""
    date: date
    metric: str
    value: float
    unit: str
    goal_title: str
    collected_at: datetime | None = None

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        d = asdict(self)
        d["date"] = self.date.isoformat()
        if self.collected_at is not None:
            d["collected_at"] = self.collected_at.isoformat()
        return d

    @classmethod
    def from_json(cls, data: dict) -> "MeasurementEntry":
        """Deserialize from a JSON-compatible dict."""
        return cls(
            date=date.fromisoformat(data["date"]),
            metric=data["metric"],
            value=float(data["value"]),
            unit=data["unit"],
            goal_title=data["goal_title"],
            collected_at=datetime.fromisoformat(data["collected_at"]) if data.get("collected_at") else None,
        )


def load_entries(path: Path | None = None) -> list[MeasurementEntry]:
    """Load all entries from the JSONL file.

    Returns [] if file is missing or empty.
    """
    log_path = path if path is not None else MEASUREMENTS_PATH
    if not log_path.exists():
        return []

    entries: list[MeasurementEntry] = []
    with log_path.open() as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entries.append(MeasurementEntry.from_json(json.loads(stripped)))
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed measurement entry at line {line_num}: {e}")

    return entries


def find_last_entry(
    entries: list[MeasurementEntry],
    goal_title: str,
    metric: str,
) -> MeasurementEntry | None:
    """Return the most recent entry for a given goal + metric, or None."""
    matching = [e for e in entries if e.goal_title == goal_title and e.metric == metric]
    if not matching:
        return None
    return max(matching, key=lambda e: e.date)


def find_entries_since(
    entries: list[MeasurementEntry],
    goal_title: str,
    metric: str,
    since: date,
) -> list[MeasurementEntry]:
    """Return all entries on or after `since` for a given goal + metric."""
    return [
        e for e in entries
        if e.goal_title == goal_title and e.metric == metric and e.date >= since
    ]


def append_entry(path: Path, entry: MeasurementEntry) -> None:
    """Append a single entry to the JSONL file. Creates file if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry.to_json()) + "\n")
