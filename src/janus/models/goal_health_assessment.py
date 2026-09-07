"""Goal health assessment model for Janus.

A ``GoalHealthAssessment`` is the derived, on-demand snapshot of a single
goal's health state — the composite label (healthy | watch | stalled |
completed) plus the signals that produced it and supporting metrics.

Health state is a derived attribute: it is computed from current signals
and is NOT persisted (design §13.1).

This implements the assessment data model defined in
``docs/goal_health_progress_signals_stalled_detection_spec.md`` §5.4.
"""

from dataclasses import dataclass, field
from datetime import datetime

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
