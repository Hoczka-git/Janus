"""Strategic summary data models for Janus.

A ``StrategicSummary`` is an aggregated, on-demand snapshot of the goal
portfolio's strategic health — which goals are neglected or stalled, what
the recommended next actions are, and which cross-domain knowledge artifacts
are linked to each goal.

Implements the data model defined in
``docs/design/strategic_summary_spec.md`` §5 (Models).

Health state and signals are *derived*, not persisted (design §13.1). The
strategic summary is a pure aggregation over ``GoalHealthAssessment``,
``GoalReview``, attention items, recommendations, and cross-domain links.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StalledGoal:
    """A goal whose health state is ``stalled`` (no forward momentum).

    Derived from ``assess_goal_health()``. Stalled means the dominant signal
    maps to ``stalled`` in the health-state resolution (§4.2) — e.g.
    ``goal_overdue``, ``goal_stalled``, ``milestone_slipped``,
    ``no_recent_activity``.
    """

    goal_title: str
    health_state: str  # "stalled"
    dominant_signal: str       # signal identifier (e.g. "goal_overdue")
    dominant_signal_score: int
    dominant_signal_reason: str
    progress: float | None = None           # current progress percentage
    progress_delta: float | None = None     # delta over 14-day lookback
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0


@dataclass
class NeglectedGoal:
    """A goal that is at-risk (``watch`` or ``stalled``) with insufficient
    strategic attention relative to severity (design §2).

    A goal is included in the neglected list when:
      - ``health_state`` is ``watch`` or ``stalled`` (i.e. != ``healthy``), AND
      - at least one of:
        - ``days_since_last_activity`` > ``inactivity_window_days``
          (per-goal override or system default 30)
        - ``measurement_overdue_count`` > 0
        - no open related tasks exist AND no upcoming milestone/deadline exists
    """

    goal_title: str
    health_state: str  # "watch" | "stalled"
    dominant_signal: str
    dominant_signal_score: int
    dominant_signal_reason: str
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0
    has_open_related_tasks: bool = True
    has_upcoming_deadline: bool = True


@dataclass
class CrossDomainLink:
    """A cross-domain knowledge artifact linked to a goal.

    Categories (design §4, §82):
      - ``research_artifact`` — from ``ResearchArtifact.linked_goal_titles``
      - ``decision`` — from ``Decision.goal_titles`` (ADR)
      - ``follow_up`` — from ``FollowUp.linked_goal_title``
    """

    goal_title: str
    category: str  # "research_artifact" | "decision" | "follow_up"
    title: str     # artifact title, decision title, or follow-up title


@dataclass
class RecommendedAction:
    """A ranked recommendation for a neglected or stalled goal (design §4).

    Format per spec §4.10:
    ``{goal_title} [{health_state}, score={dominant_signal_score}]``
    """

    goal_title: str
    health_state: str
    dominant_signal: str
    dominant_signal_score: int
    dominant_signal_reason: str
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0
    suggested_next_step: str | None = None
    attention_reason: str | None = None
    cross_links: list[CrossDomainLink] = field(default_factory=list)


@dataclass
class PortfolioHealthCounts:
    """Counts of goals by health state (design §5 Model)."""

    total_active: int = 0
    healthy: int = 0
    watch: int = 0
    stalled: int = 0
    completed: int = 0
    inactive: int = 0


@dataclass
class StrategicSummary:
    """Aggregated strategic view of the goal portfolio (design §5).

    Fields:
        generated_at: When this summary was computed.
        portfolio_health_counts: Goal counts by health state.
        stalled_goals: All goals with ``health_state == stalled``, sorted by
            dominant signal score descending (design §3).
        neglected_goals: At-risk goals with insufficient attention, severity-
            ranked (stalled > watch) (design §2).
        recommended_actions: Ranked recommendations, one per neglected/stalled
            goal (design §4).
        cross_domain_links: All cross-domain links for goals in the summary
            (design §82).
    """

    generated_at: datetime
    portfolio_health_counts: PortfolioHealthCounts
    stalled_goals: list[StalledGoal] = field(default_factory=list)
    neglected_goals: list[NeglectedGoal] = field(default_factory=list)
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    cross_domain_links: list[CrossDomainLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (design §5, §73)."""
        from dataclasses import asdict
        return asdict(self)
