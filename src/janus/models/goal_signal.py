"""Goal signal dataclass — a single signal emitted for a goal at a point in time."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class GoalSignal:
    """A single signal emitted for a goal at a point in time.

    Attributes:
        signal: Signal identifier (matches StallSignal.signal).
        score: Severity score (higher = more severe).
        reason: Human-readable explanation.
        timestamp: When the signal was evaluated.
        stale_after: Optional auto-resolve duration (not used in v1).
    """

    signal: str
    score: int
    reason: str
    timestamp: datetime
    stale_after: timedelta | None = None
