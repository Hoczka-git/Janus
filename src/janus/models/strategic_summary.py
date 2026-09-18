"""Strategic state and summary data models for Janus.

Defines the data structures for strategic state summaries and meaningful
change detection, as specified in ``docs/design/strategic_summary_spec.md``.

A ``StrategicSummary`` is an aggregated, on-demand snapshot of the goal
portfolio's strategic health — which goals are neglected or stalled, what
the recommended next actions are, and which cross-domain knowledge artifacts
are linked to each goal.

A ``StrategicStateSnapshot`` is a point-in-time capture of the strategic
state of all active goals. By comparing two snapshots, the change-detection
service can identify meaningful changes in the strategic picture.

Health state and signals are derived, not persisted.
"""

from dataclasses import dataclass, field
from datetime import datetime


# ── Meaningful change types ──────────────────────────────────────────────────
#
# Each enum value corresponds to a criterion in design spec §1 "Meaningful
# change (what triggers a strategic summary update)".

CHANGE_HEALTH_STATE = "health_state_transition"
CHANGE_DOMINANT_SIGNAL_SCORE = "dominant_signal_score_change"
CHANGE_PROGRESS_DELTA = "progress_delta_threshold_cross"
CHANGE_STALLED_SIGNAL = "stalled_signal_activated_or_cleared"
CHANGE_MEASUREMENT_DUE = "measurement_requirement_overdue_fired_or_satisfied"
CHANGE_GOAL_STATUS = "goal_status_transition"
CHANGE_MILESTONE_STATUS = "milestone_status_changed"
CHANGE_CROSS_DOMAIN_LINK = "cross_domain_link_changed"

# All valid change types, for validation / iteration.
ALL_CHANGE_TYPES = (
    CHANGE_HEALTH_STATE,
    CHANGE_DOMINANT_SIGNAL_SCORE,
    CHANGE_PROGRESS_DELTA,
    CHANGE_STALLED_SIGNAL,
    CHANGE_MEASUREMENT_DUE,
    CHANGE_GOAL_STATUS,
    CHANGE_MILESTONE_STATUS,
    CHANGE_CROSS_DOMAIN_LINK,
)

# Signals that count as "stalled-work signals" for §1 criterion 3.
_STALLED_SIGNALS = frozenset({
    "goal_stalled",
    "goal_overdue",
    "milestone_slipped",
    "no_recent_activity",
})


@dataclass
class GoalStateSnapshot:
    """Point-in-time strategic state of a single goal.

    This is a lightweight, hashable-by-construction view of a goal's
    strategic-relevant fields, designed to be cheap to construct and
    compare. It captures exactly the fields the meaningful-change detector
    needs — no more — so snapshots are not coupled to the full ``Goal``
    model.
    """

    goal_title: str
    health_state: str | None = None
    dominant_signal: str | None = None
    dominant_signal_score: int = 0
    progress: float | None = None
    progress_delta: float | None = None
    measurement_overdue_count: int = 0
    signals: frozenset[str] = field(default_factory=frozenset)
    goal_status: str = "active"
    milestone_statuses: dict[str, str] = field(default_factory=dict)
    linked_research_artifacts: list[str] = field(default_factory=list)
    linked_decision_numbers: list[str] = field(default_factory=list)
    linked_followup_ids: list[str] = field(default_factory=list)


@dataclass
class MeaningfulChange:
    """A single meaningful change detected in strategic state."""

    change_type: str
    goal_title: str
    description: str
    severity: int = 0
    details: dict = field(default_factory=dict)
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.change_type not in ALL_CHANGE_TYPES:
            raise ValueError(
                f"Invalid change_type: {self.change_type!r}. "
                f"Allowed: {', '.join(ALL_CHANGE_TYPES)}"
            )


@dataclass
class StrategicStateSnapshot:
    """A point-in-time capture of the strategic state across all goals."""

    generated_at: datetime
    goals: list[GoalStateSnapshot] = field(default_factory=list)

    def goal_by_title(self, title: str) -> GoalStateSnapshot | None:
        """Look up a goal in this snapshot by title."""
        for goal in self.goals:
            if goal.goal_title == title:
                return goal
        return None


# ── Strategic summary models ─────────────────────────────────────────────────


@dataclass
class StalledGoal:
    """A goal whose health state is ``stalled`` (no forward momentum)."""

    goal_title: str
    health_state: str
    dominant_signal: str
    dominant_signal_score: int
    dominant_signal_reason: str
    progress: float | None = None
    progress_delta: float | None = None
    days_since_last_activity: int | None = None
    measurement_overdue_count: int = 0


@dataclass
class NeglectedGoal:
    """A goal that is at-risk with insufficient strategic attention."""

    goal_title: str
    health_state: str
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

    Categories:
      - ``research_artifact``
      - ``decision``
      - ``follow_up``
    """

    goal_title: str
    category: str
    title: str


@dataclass
class RecommendedAction:
    """A ranked recommendation for a neglected or stalled goal."""

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
    """Counts of goals grouped by health state."""

    total_active: int = 0
    healthy: int = 0
    watch: int = 0
    stalled: int = 0
    completed: int = 0
    inactive: int = 0

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


@dataclass
class StrategicSummary:
    """Aggregated strategic view of the goal portfolio."""

    generated_at: datetime
    portfolio_health_counts: PortfolioHealthCounts
    stalled_goals: list[StalledGoal] = field(default_factory=list)
    neglected_goals: list[NeglectedGoal] = field(default_factory=list)
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    cross_domain_links: list[CrossDomainLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""

        from dataclasses import asdict

        return asdict(self)