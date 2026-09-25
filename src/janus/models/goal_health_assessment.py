"""Goal health assessment model for Janus.

A ``GoalHealthAssessment`` is the derived, on-demand snapshot of a single
goal's health state — the composite label (healthy | watch | stalled |
completed) plus the signals that produced it and supporting metrics.

Health state is a derived attribute: it is computed from current signals
and is NOT persisted (design §13.1).

This implements the assessment data model defined in
``docs/design/goal_health_progress_signals_stalled_detection_spec.md`` §5.4.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from janus.models.goal_signal import GoalSignal


@dataclass
class GoalHealthAssessment:
    """The computed health assessment for a single goal.

    Health state is a derived attribute — it is computed on demand from
    current signals and NOT persisted (design §13.1).

    Attributes:
        goal_title: The goal being assessed (identity is the title string).
        health_state: healthy | watch | stalled | completed. Derived from
            the highest-severity signal (design §4.2).
        signals: All signals that fired for this goal in the assessment.
        dominant_signal: The highest-severity signal (None when healthy).
        progress: Current progress as a percentage, from
            ``compute_goal_progress``. None if not computable.
        progress_delta: Change in progress over the lookback window
            (design §8.2). None if not computable (e.g. insufficient
            history, inactive/completed goal).
        days_since_last_activity: Days since the most recent metric
            snapshot or task completion. None if no activity data exists.
        measurement_overdue_count: Number of measurement requirements
            currently overdue (design §9).
        evaluated_at: When this assessment was computed.
    """

    goal_title: str
    health_state: str  # healthy | watch | stalled | completed
    signals: list[GoalSignal] = field(default_factory=list)
    dominant_signal: GoalSignal | None = None
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0
    evaluated_at: datetime | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (spec §73).

        Converts ``datetime`` to ISO-format strings, ``timedelta`` to
        total seconds, and includes the ``category`` field on each
        signal.
        """
        def _signal_dict(signal: GoalSignal) -> dict:
            ts = signal.timestamp
            stale = signal.stale_after
            return {
                "signal": signal.signal,
                "category": signal.category,
                "score": signal.score,
                "reason": signal.reason,
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
                "stale_after": (
                    stale.total_seconds()
                    if isinstance(stale, timedelta)
                    else stale
                ),
            }

        return {
            "goal_title": self.goal_title,
            "health_state": self.health_state,
            "signals": [_signal_dict(s) for s in self.signals],
            "dominant_signal": (
                _signal_dict(self.dominant_signal)
                if self.dominant_signal is not None
                else None
            ),
            "progress": self.progress,
            "progress_delta": self.progress_delta,
            "days_since_last_activity": self.days_since_last_activity,
            "measurement_overdue_count": self.measurement_overdue_count,
            "evaluated_at": (
                self.evaluated_at.isoformat()
                if isinstance(self.evaluated_at, datetime)
                else self.evaluated_at
            ),
        }
