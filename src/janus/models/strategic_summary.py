"""Strategic summary data model for Janus (design spec §5).

A ``StrategicSummary`` is the structured, on-demand snapshot of the whole
portfolio's strategic state — health counts, stalled and neglected goals,
and ranked recommended next actions with cross-domain links.

Health state and signals are *derived* (design §13.1), so the summary is a
consumption format assembled from existing services rather than a persisted
record. This model is a pure addition — no existing surfaces change (§83).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PortfolioHealthCounts:
    """Counts of goals grouped by health state (spec §5, §6.7).

    Attributes:
        total_active: Number of goals with status ``active``.
        healthy: Active goals with ``health_state == healthy``.
        watch: Active goals with ``health_state == watch``.
        stalled: Active goals with ``health_state == stalled``.
        completed: Goals with status ``completed``.
        inactive: Goals with status ``inactive`` (excluded from health eval).
    """

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
    """The strategic next-action summary for the goal portfolio (spec §5).

    Aggregates the outputs of:
    - ``assess_goal_health()`` → health state + dominant signal (§4 source 1)
    - ``get_attention_items()`` → dominant attention category + reason (§4)
    - ``GoalReview.suggested_next_step`` (via weekly review / next_action)
    - ``recommendations`` service → task-level recommendations (§4 source 3)
    - cross-domain links → research artifacts, decisions, follow-ups (§4, §82)

    Attributes:
        generated_at: When this summary was computed.
        portfolio_health_counts: Counts of goals by health state.
        stalled_goals: All goals with ``health_state == stalled``, sorted by
            dominant signal score descending (spec §3.9).
        neglected_goals: Goals meeting the neglected threshold (spec §26):
            health == watch/stalled AND (inactive > window OR measurement
            overdue > 0 OR no open tasks with upcoming milestone/deadline).
            Excludes ``inactive`` and ``completed`` goals (spec §80).
        recommended_actions: Ranked next-action recommendations, one per
            stalled/neglected goal (spec §4, §61).
        cross_domain_links: All cross-domain links surfaced for the goals in
            the summary (spec §4, §82).
    """

    generated_at: datetime | None = None
    portfolio_health_counts: PortfolioHealthCounts = field(default_factory=PortfolioHealthCounts)
    stalled_goals: list = field(default_factory=list)
    neglected_goals: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    cross_domain_links: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (spec §73).

        Health assessments and recommended actions already expose ``to_dict``
        (or are dataclasses via ``asdict``); cross-domain links likewise.
        """
        from dataclasses import asdict
        d = asdict(self)
        # generated_at may be a datetime; keep it as-is (isoformat at JSON
        # serialization time by the caller) but normalize to dict shape.
        return d
