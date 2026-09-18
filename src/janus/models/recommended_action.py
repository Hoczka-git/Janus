"""Recommended next-action data model for Janus.

A ``RecommendedAction`` is a single ranked, actionable recommendation tied
to a neglected or stalled goal, synthesized from multiple state-summary
sources (spec ``docs/design/strategic_summary_spec.md`` §4).

The recommendation engine (``services/recommended_actions.py``) aggregates:
- ``assess_goal_health()`` output → health state + dominant signal
- ``GoalReview.suggested_next_step`` (via ``services/next_action.py``)
- ``recommendations`` service → task-level ranked recommendations
- ``attention`` items → dominant attention category + reason
- cross-domain links → research artifacts, decisions, follow-ups

Health state and signals are *derived* (design §13.1); this model is a
consumption format for surfacing them as actionable items.
"""

from dataclasses import dataclass, field
from datetime import datetime

from janus.models.goal_signal import GoalSignal


@dataclass
class CrossDomainLink:
    """A cross-domain knowledge artifact linked to a goal (spec §4, §82).

    Categories:
      - ``research_artifact`` — from ``ResearchArtifact.linked_goal_titles``
      - ``decision`` — from ``Decision.goal_titles`` (ADR)
      - ``follow_up`` — from ``FollowUp.linked_goal_title``
    """

    goal_title: str
    category: str  # "research_artifact" | "decision" | "follow_up"
    title: str     # artifact title, decision title, or follow-up title


@dataclass
class TaskRecommendation:
    """A task-level recommendation surfaced for a goal (spec §4 source 3).

    Produced by the ``recommendations`` service (``recommend_next_actions``).
    """

    title: str
    score: int
    reason: str
    due_date: str | None = None
    priority: int | None = None


@dataclass
class RecommendedAction:
    """A ranked next-action recommendation for a neglected/stalled goal.

    One per neglected/stalled goal, ranked by severity (spec §4, §43–§61).

    Format per spec §4.10:
        {goal_title} [{health_state}, score={dominant_signal_score}]
          Reason: {dominant_signal_reason}
          Progress: {current_progress}% (delta {progress_delta}% over 14d)
          Activity: {days_since_last_activity}d since last metric/task
          Measurements overdue: {measurement_overdue_count}
          Suggested action: {suggested_next_step or attention_item.reason}
          Cross-links: {research_artifact, decision, follow_up}
    """

    goal_title: str
    health_state: str
    dominant_signal: str = ""
    dominant_signal_score: int = 0
    dominant_signal_reason: str = ""
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0
    suggested_next_step: str | None = None
    attention_reason: str | None = None
    task_recommendations: list[TaskRecommendation] = field(default_factory=list)
    cross_links: list[CrossDomainLink] = field(default_factory=list)
    generated_at: datetime | None = None

    @property
    def suggested_action(self) -> str | None:
        """The best available suggested action for this goal (spec §4, §57).

        Priority order:
        1. ``suggested_next_step`` (from GoalReview / next_action service)
        2. ``attention_reason`` (from attention items)
        """
        if self.suggested_next_step:
            return self.suggested_next_step
        if self.attention_reason:
            return self.attention_reason
        return None

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict
        return asdict(self)
