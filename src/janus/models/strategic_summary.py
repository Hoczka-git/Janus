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
# goal_stalled, goal_overdue, milestone_slipped, no_recent_activity.
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

    Attributes:
        goal_title: Goal title (identity).
        health_state: healthy | watch | stalled | completed | None if
            not assessed (e.g. inactive goal excluded).
        dominant_signal: The highest-severity signal identifier, or None.
        dominant_signal_score: Score of the dominant signal (0 if None).
        progress: Current progress percentage, or None if not computable.
        progress_delta: Change in progress over the 14-day lookback, or None.
        measurement_overdue_count: Overdue measurement requirements count.
        signals: Frozen set of signal identifiers that fired.
        goal_status: active | completed | inactive (the Goal.status field).
        milestone_statuses: Dict mapping milestone title → status, for
            milestone status change detection (§1 criterion 6).
        linked_research_artifacts: Sorted list of linked research artifact
            titles (for cross-domain link change detection, §1 criterion 5).
        linked_decision_numbers: Sorted list of linked ADR numbers.
        linked_followup_ids: Sorted list of linked follow-up IDs.
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
    """A single meaningful change detected in strategic state.

    One ``MeaningfulChange`` corresponds to exactly one criterion from
    design spec §1. A single comparison between two snapshots may produce
    multiple changes (e.g. a goal both transitions health state *and*
    sees its measurement requirement fire).

    Attributes:
        change_type: One of the ``CHANGE_*`` constants above.
        goal_title: The goal whose strategic state changed.
        description: Human-readable summary of the change.
        severity: Relative severity for sorting (higher = more important).
        details: Optional dict with additional machine-readable context
            (e.g. old_health_state, new_health_state, old_score, new_score).
        timestamp: When this change was detected.
    """

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
    """A point-in-time capture of the strategic state across all goals.

    Composed of per-goal ``GoalStateSnapshot`` entries. The change detector
    compares a previous snapshot against a current one to produce
    ``MeaningfulChange`` events.

    Attributes:
        generated_at: When this snapshot was taken.
        goals: List of ``GoalStateSnapshot``, one per goal assessed.
    """

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
    """A goal whose health state is ``stalled`` (no forward momentum).

    Derived from ``assess_goal_health()``. Stalled means the dominant signal
    maps to ``stalled`` in the health-state resolution (§4.2) — e.g.
    ``goal_overdue``, ``goal_stalled``, ``milestone_slipped``,
    ``no_recent_activity``.
    """

    goal_title: str
    health_state: str  # "stalled"
    dominant_signal: str
    dominant_signal_score: int
    dominant_signal_reason: str
    progress: float | None = None
    progress_delta: float | None = None
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