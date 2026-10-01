"""Personal State aggregate root data model for Janus.

Defines the ``PersonalState`` dataclass — a read-model aggregate that
provides a unified, consistent view of the user's goals, tasks,
commitments, and activities without replacing the underlying domain
models.

Also defines the ``PersonalStateStatus`` enum for the overall state
classification, and transition rules for constituent entity states.

Spec: ``docs/design/personal_state_model_spec.md``
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.workout import Workout
from janus.models.decision import Decision
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.strategic_summary import (
    StrategicSummary,
    RecommendedAction,
)
from janus.models.commitment import Commitment
from janus.models.routine import Routine
from janus.models.constraint import Constraint
from janus.models.preference import Preference
from janus.models.resource import Resource


# ── Personal state status enum ───────────────────────────────────────────────


class PersonalStateStatus(StrEnum):
    """Overall classification of the personal state.

    Derived from the aggregate's constituents — goal health, task
    backlog, and integrity issues. This is a read-only classification;
    it does not drive any write operations.
    """

    HEALTHY = "healthy"
    """No stalled goals, no blocked tasks, no integrity errors."""

    ATTENTION_NEEDED = "attention_needed"
    """Some goals are stalled or some tasks are blocked, but no errors."""

    CRITICAL = "critical"
    """Integrity errors exist (orphan tasks, invalid references, etc.)."""

    EMPTY = "empty"
    """No goals, no tasks, no followups — fresh start state."""


# ── Transition rules ─────────────────────────────────────────────────────────

#: Valid goal status transitions.
#: active → completed, active → inactive, inactive → active, completed → active
GOAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "active": {"completed", "inactive"},
    "inactive": {"active"},
    "completed": {"active"},
}

#: Valid task state transitions.
#: todo → in_progress, todo → blocked, in_progress → blocked,
#: blocked → in_progress, in_progress → todo (reopen)
TASK_STATE_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"in_progress", "blocked"},
    "in_progress": {"blocked", "todo"},
    "blocked": {"in_progress", "todo"},
}

#: Valid follow-up state transitions.
#: pending → scheduled, pending → in_progress, scheduled → in_progress,
#: in_progress → blocked, blocked → in_progress, in_progress → completed,
#: blocked → completed, scheduled → deferred, pending → deferred
FOLLOWUP_STATE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"scheduled", "in_progress", "deferred"},
    "scheduled": {"in_progress", "deferred"},
    "in_progress": {"blocked", "completed"},
    "blocked": {"in_progress", "completed"},
    "completed": set(),
    "deferred": {"pending"},
}


def is_valid_goal_transition(from_status: str, to_status: str) -> bool:
    """Return True if the goal status transition is valid."""
    return to_status in GOAL_STATUS_TRANSITIONS.get(from_status, set())


def is_valid_task_transition(from_state: str, to_state: str) -> bool:
    """Return True if the task state transition is valid."""
    return to_state in TASK_STATE_TRANSITIONS.get(from_state, set())


def is_valid_followup_transition(from_state: str, to_state: str) -> bool:
    """Return True if the follow-up state transition is valid."""
    return to_state in FOLLOWUP_STATE_TRANSITIONS.get(from_state, set())


# ── PersonalState aggregate root ─────────────────────────────────────────────


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
    measurement_requirements: list[dict[str, Any]] = field(default_factory=list)

    # Activity and evidence
    recent_activity: list[RecentActivityEntry] = field(default_factory=list)
    workouts: list[Workout] = field(default_factory=list)

    # Knowledge and decisions
    decisions: list[Decision] = field(default_factory=list)
    research_artifacts: list[str] = field(default_factory=list)

    # Personal state entities (Phase C)
    commitments: list[Commitment] = field(default_factory=list)
    routines: list[Routine] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)

    # Strategic view (derived)
    strategic_summary: StrategicSummary | None = None
    recommended_actions: list[RecommendedAction] = field(default_factory=list)

    # Cross-cutting invariants
    integrity_issues: list[GoalIntegrityIssue] = field(default_factory=list)

    # Overall state classification
    status: PersonalStateStatus = PersonalStateStatus.HEALTHY

    def __post_init__(self) -> None:
        """Validate the aggregate after construction."""
        if not self.data_fingerprint or not self.data_fingerprint.strip():
            raise ValueError("data_fingerprint must not be empty")
        if not isinstance(self.status, PersonalStateStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in PersonalStateStatus)}"
            )

    @property
    def is_empty(self) -> bool:
        """True if the state has no goals, tasks, or followups."""
        return not self.goals and not self.tasks and not self.followups

    @property
    def has_integrity_errors(self) -> bool:
        """True if any integrity issues with error severity exist."""
        return any(i.severity == "error" for i in self.integrity_issues)

    @property
    def goal_count(self) -> int:
        return len(self.goals)

    @property
    def active_goal_count(self) -> int:
        return len(self.active_goals)

    @property
    def open_task_count(self) -> int:
        return len(self.open_tasks)

    @property
    def blocked_task_count(self) -> int:
        return len(self.blocked_tasks)

    @property
    def followup_count(self) -> int:
        return len(self.followups)

    @property
    def inbox_count(self) -> int:
        return len(self.inbox_items)

    @property
    def integrity_error_count(self) -> int:
        return sum(1 for i in self.integrity_issues if i.severity == "error")

    @property
    def integrity_warning_count(self) -> int:
        return sum(1 for i in self.integrity_issues if i.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        return _jsonize(raw)


def _jsonize(obj: Any) -> Any:
    """Recursively convert datetimes and enums to JSON-friendly values."""
    if isinstance(obj, dict):
        return {k: _jsonize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonize(item) for item in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, StrEnum):
        return obj.value
    return obj
