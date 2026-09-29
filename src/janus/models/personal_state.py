"""Personal State aggregate root for Janus.

Defines the ``PersonalState`` read-model aggregate that unifies existing
domain models (Goal, Task, FollowUp, InboxItem, Decision, Workout, etc.)
into a single, consistent view of the user's personal state.

PersonalState is a **read-model aggregate** — it is constructed on demand
from the canonical markdown data files and is not itself persisted. It
serves as the substrate for:

- Agency-aware planning (Phase D)
- Strategic summaries and reviews
- Cross-cutting invariant checks
- Next-action derivation

Design reference: ``docs/design/personal_state_model_spec.md``
"""

from dataclasses import dataclass, field
from datetime import datetime

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.decision import Decision
from janus.models.workout import Workout
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary
from janus.models.recommended_action import RecommendedAction


@dataclass
class PersonalState:
    """Aggregate root for the user's current personal state.

    This is a READ-MODEL aggregate — it provides a unified, consistent
    view of the user's goals, tasks, commitments, and activities without
    replacing the underlying domain models.

    The aggregate is constructed on demand from the canonical data files
    and is not itself persisted. It serves as the substrate for:

    - Agency-aware planning (Phase D)
    - Strategic summaries and reviews
    - Cross-cutting invariant checks
    - Next-action derivation

    Attributes:
        generated_at: When this aggregate was constructed.
        data_fingerprint: Hash of source data files for cache invalidation.
        goals: All goals loaded from data/goals.md.
        active_goals: Derived — goals with status == "active".
        stalled_goals: Derived — goals with health signals indicating stall.
        neglected_goals: Derived — goals with inactivity signals.
        tasks: All open tasks loaded from data/tasks.md.
        open_tasks: Derived — tasks in ALLOWED_STATES.
        blocked_tasks: Derived — tasks with state == "blocked".
        followups: All follow-ups from data/followups.md.
        inbox_items: All inbox items from data/inbox.md.
        milestones: Derived from goals — all milestones across all goals.
        projects: Derived from goals — all projects across all goals.
        metric_snapshots: Metric snapshots from data/metric_history.md.
        measurement_requirements: Derived from goals.
        recent_activity: Derived from goals — all recent activity entries.
        workouts: All workouts from data/workouts/.
        decisions: All decisions from docs/decisions/.
        research_artifacts: Titles of research artifacts linked to goals.
        strategic_summary: Computed strategic summary (optional).
        recommended_actions: Computed recommended actions (optional).
        integrity_issues: Issues from goal integrity audit.
    """

    # Core identity
    generated_at: datetime
    data_fingerprint: str

    # Goal portfolio
    goals: list[Goal] = field(default_factory=list)
    active_goals: list[Goal] = field(default_factory=list)
    stalled_goals: list[Goal] = field(default_factory=list)
    neglected_goals: list[Goal] = field(default_factory=list)

    # Work items
    tasks: list[Task] = field(default_factory=list)
    open_tasks: list[Task] = field(default_factory=list)
    blocked_tasks: list[Task] = field(default_factory=list)

    # Commitments and intentions
    followups: list[FollowUp] = field(default_factory=list)
    inbox_items: list[InboxItem] = field(default_factory=list)

    # Execution structure
    milestones: list[Milestone] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)

    # Progress measurement
    metric_snapshots: list[MetricSnapshot] = field(default_factory=list)
    measurement_requirements: list[dict] = field(default_factory=list)

    # Activity and evidence
    recent_activity: list[RecentActivityEntry] = field(default_factory=list)
    workouts: list[Workout] = field(default_factory=list)

    # Knowledge and decisions
    decisions: list[Decision] = field(default_factory=list)
    research_artifacts: list[str] = field(default_factory=list)

    # Strategic view (derived)
    strategic_summary: StrategicSummary | None = None
    recommended_actions: list[RecommendedAction] = field(default_factory=list)

    # Cross-cutting invariants
    integrity_issues: list[GoalIntegrityIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Converts ``datetime`` to ISO-format strings.
        """
        from dataclasses import asdict

        raw: dict = asdict(self)
        return _jsonize(raw)


def _jsonize(obj):
    """Recursively convert datetimes to ISO strings for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _jsonize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonize(item) for item in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj
