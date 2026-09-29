"""Personal State aggregate root for Janus.

PersonalState is a READ-MODEL aggregate that provides a unified, consistent
view of the user's goals, tasks, commitments, and activities without
replacing the underlying domain models.

The aggregate is constructed on demand from the canonical data files
and is not itself persisted. It serves as the substrate for:
- Agency-aware planning (Phase D)
- Strategic summaries and reviews
- Cross-cutting invariant checks
- Next-action derivation

Spec: docs/design/personal_state_model_spec.md
"""

from dataclasses import dataclass, field
from datetime import datetime

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary, RecommendedAction


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
    """

    # Core identity
    generated_at: datetime
    data_fingerprint: str  # hash of source data files for cache invalidation

    # Goal portfolio
    goals: list[Goal] = field(default_factory=list)
    active_goals: list[Goal] = field(default_factory=list)           # derived: status == "active"
    stalled_goals: list[Goal] = field(default_factory=list)          # derived: health signals
    neglected_goals: list[Goal] = field(default_factory=list)        # derived: inactivity signals

    # Work items
    tasks: list[Task] = field(default_factory=list)
    open_tasks: list[Task] = field(default_factory=list)             # derived: state in ALLOWED_STATES
    blocked_tasks: list[Task] = field(default_factory=list)          # derived: state == "blocked"

    # Commitments and intentions
    followups: list[FollowUp] = field(default_factory=list)
    inbox_items: list[InboxItem] = field(default_factory=list)

    # Execution structure
    milestones: list[Milestone] = field(default_factory=list)        # derived from goals
    projects: list[Project] = field(default_factory=list)            # derived from goals/milestones

    # Progress measurement
    metric_snapshots: list[MetricSnapshot] = field(default_factory=list)
    measurement_requirements: list[dict] = field(default_factory=list)  # derived from goals

    # Activity and evidence
    recent_activity: list[RecentActivityEntry] = field(default_factory=list)
    workouts: list = field(default_factory=list)  # list[Workout] — placeholder for Phase 5

    # Knowledge and decisions
    decisions: list = field(default_factory=list)  # list[Decision]
    research_artifacts: list[str] = field(default_factory=list)      # titles linked to goals

    # Strategic view (derived)
    strategic_summary: StrategicSummary | None = None
    recommended_actions: list[RecommendedAction] = field(default_factory=list)

    # Cross-cutting invariants
    integrity_issues: list[GoalIntegrityIssue] = field(default_factory=list)  # from goal_integrity audit

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        return _jsonize(raw)  # type: ignore[return-value]


def _jsonize(obj):
    """Recursively convert datetimes to ISO strings for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _jsonize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonize(item) for item in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj
