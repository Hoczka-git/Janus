"""Goal health assessment dataclass — the computed health assessment for a goal."""

from dataclasses import dataclass
from datetime import datetime

from janus.models.goal_signal import GoalSignal


@dataclass
class GoalHealthAssessment:
    """The computed health assessment for a single goal.

    Health state is a derived attribute — it is computed on demand from
    current signals and NOT persisted (design §13.1).

    Attributes:
        goal_title: Title of the assessed goal.
        health_state: One of healthy | watch | stalled | completed.
        signals: All signals that fired for this goal.
        dominant_signal: Highest-severity signal (None if healthy).
        progress: Current progress % from compute_goal_progress.
        progress_delta: Change in progress over the lookback window.
        days_since_last_activity: Days since last metric update or task completion.
        measurement_overdue_count: Number of overdue measurement requirements.
        evaluated_at: When the assessment was computed.
    """

    goal_title: str
    health_state: str                    # healthy | watch | stalled | completed
    signals: list[GoalSignal]            # all signals that fired
    dominant_signal: GoalSignal | None   # highest-severity signal (None if healthy)
    progress: float | None               # current progress % (from compute_goal_progress)
    progress_delta: float | None         # change in progress over lookback window
    days_since_last_activity: int | None # days since last metric update or task completion
    measurement_overdue_count: int       # number of overdue measurement requirements
    evaluated_at: datetime
