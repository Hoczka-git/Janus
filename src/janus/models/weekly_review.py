"""Weekly review data models."""

from dataclasses import dataclass, field

from janus.models.goal import Goal


@dataclass
class GoalReview:
    goal: Goal
    progress: float | None = None          # from compute_goal_progress
    progress_detail: str | None = None     # human-readable, NO duplicate %
    completed_related_tasks: list[str] = field(default_factory=list)
    missing_related_tasks: list[str] = field(default_factory=list)
    suggested_next_step: str | None = None
    all_related_tasks_completed: bool = False
    health_state: str | None = None        # healthy | watch | stalled | completed
    days_since_last_activity: int | None = None
    progress_delta: float | None = None    # progress change over lookback window


@dataclass
class WeeklyReview:
    completed_tasks: list[str] = field(default_factory=list)
    open_tasks: list[str] = field(default_factory=list)
    goals: list[GoalReview] = field(default_factory=list)
