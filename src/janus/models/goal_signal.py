"""Goal progress signal model for Janus.

A ``GoalSignal`` is a single data point emitted for a goal at a point in
time — a deadline miss, a stall warning, slow progress, an overdue
measurement, or an inactivity indicator. Signals are the inputs that feed
health-state resolution (see ``models/goal_health_assessment.py``).

This implements the signal data model defined in
``docs/goal_health_progress_signals_stalled_detection_spec.md`` §5.2.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class GoalSignal:
    """A single signal emitted for a goal at a point in time.

    Multiple signals can fire for the same goal; the highest-severity
    signal determines the health state.

    Attributes:
        signal: Signal identifier (matches ``StallSignal.signal`` from the
            attention engine and the spec's signal taxonomy).
        score: Severity score (higher = more severe). Used as the
            tiebreaker and to map the signal to a health state.
        reason: Human-readable explanation of why the signal fired.
        timestamp: When the signal was evaluated.
        stale_after: Optional duration after which the signal auto-resolves.
            Not used in v1 (signals are recomputed on demand).
    """

    signal: str
    score: int
    reason: str
    timestamp: datetime
    stale_after: timedelta | None = None
