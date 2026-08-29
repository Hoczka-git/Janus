"""Weekly review data models."""

from dataclasses import dataclass

from janus.models.goal import Goal


@dataclass
class GoalReview:
    goal: Goal
    progress: bool = False
    completed_related_tasks: list[str] | None = None
    missing_related_tasks: list[str] | None = None
    suggested_next_step: str | None = None
    all_related_tasks_completed: bool = False

    def __post_init__(self):
        if self.completed_related_tasks is None:
            self.completed_related_tasks = []
        if self.missing_related_tasks is None:
            self.missing_related_tasks = []


@dataclass
class WeeklyReview:
    completed_tasks: list[str] | None = None
    open_tasks: list[str] | None = None
    goals: list[GoalReview] | None = None

    def __post_init__(self):
        if self.completed_tasks is None:
            self.completed_tasks = []
        if self.open_tasks is None:
            self.open_tasks = []
        if self.goals is None:
            self.goals = []
