"""Personal State Builder service for Janus.

Constructs the ``PersonalState`` aggregate from existing data files.
This is the repository/DAO layer for the personal state read model.

The builder reads all source data files (goals, tasks, followups, inbox,
workouts, decisions), builds domain models, derives computed views,
runs integrity checks, and returns an immutable ``PersonalState`` instance.

Design reference: ``docs/design/personal_state_model_spec.md`` §3, §5 Phase 2.
"""

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path

from janus.models.goal import Goal
from janus.models.task import Task, ALLOWED_STATES
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.decision import Decision
from janus.models.workout import Workout
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityReport, GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary
from janus.models.recommended_action import RecommendedAction
from janus.models.personal_state import PersonalState

logger = logging.getLogger(__name__)

# Project root for data-file access.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Source data files that constitute the personal state.
SOURCE_FILES = (
    "data/goals.md",
    "data/tasks.md",
    "data/followups.md",
    "data/inbox.md",
    "data/metric_history.md",
)


def _compute_data_fingerprint() -> str:
    """Compute a SHA-256 fingerprint of all source data files.

    The fingerprint is used for cache invalidation — if any source file
    changes, the fingerprint changes and the aggregate must be rebuilt.

    Files that do not exist are skipped (they contribute nothing to the
    fingerprint). This means an empty state and a missing state produce
    the same fingerprint, which is correct — both are "no data".
    """
    hasher = hashlib.sha256()
    for rel_path in SOURCE_FILES:
        file_path = PROJECT_ROOT / rel_path
        if file_path.exists():
            content = file_path.read_bytes()
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(content)
            hasher.update(b"\0")
    return hasher.hexdigest()


def _load_goals() -> list[Goal]:
    """Load goals from data/goals.md. Returns [] if file is missing."""
    try:
        from janus.integrations.markdown_goals import load_goals
        return load_goals()
    except FileNotFoundError:
        return []


def _load_tasks() -> list[Task]:
    """Load open tasks from data/tasks.md. Returns [] if file is missing."""
    try:
        from janus.integrations.markdown_tasks import load_tasks
        return load_tasks()
    except FileNotFoundError:
        return []


def _load_followups() -> list[FollowUp]:
    """Load follow-ups from data/followups.md. Returns [] if file is missing."""
    try:
        from janus.integrations.markdown_followups import load_followups
        return load_followups()
    except FileNotFoundError:
        return []


def _load_inbox_items() -> list[InboxItem]:
    """Load inbox items from data/inbox.md. Returns [] if file is missing."""
    try:
        from janus.integrations.markdown_inbox import load_inbox_items
        return load_inbox_items()
    except FileNotFoundError:
        return []


def _load_decisions() -> list[Decision]:
    """Load decisions from docs/decisions/. Returns [] if unavailable."""
    try:
        from janus.services.decisions import load_decisions
        return load_decisions()
    except (FileNotFoundError, Exception):
        return []


def _load_workouts() -> list[Workout]:
    """Load workouts from data/workouts/. Returns [] if unavailable."""
    try:
        from janus.integrations.workout_md import load_workouts
        return load_workouts()
    except (FileNotFoundError, Exception):
        return []


def _load_metric_snapshots() -> list[MetricSnapshot]:
    """Load all metric snapshots from data/metric_history.md.

    Returns [] if unavailable. Since there is no get_all_metric_snapshots,
    we load per-goal by scanning the file for unique goal titles.
    """
    try:
        from janus.integrations.metric_history import METRIC_HISTORY_PATH
        if not METRIC_HISTORY_PATH.exists():
            return []
        # Read all lines and parse snapshots
        snapshots: list[MetricSnapshot] = []
        with METRIC_HISTORY_PATH.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                from janus.integrations.metric_history import _parse_line
                snap = _parse_line(line)
                if snap is not None:
                    snapshots.append(snap)
        return snapshots
    except (FileNotFoundError, Exception):
        return []


def _derive_active_goals(goals: list[Goal]) -> list[Goal]:
    """Derive active goals (status == 'active')."""
    return [g for g in goals if g.status == "active"]


def _derive_open_tasks(tasks: list[Task]) -> list[Task]:
    """Derive open tasks (state in ALLOWED_STATES or None, which means todo)."""
    return [t for t in tasks if (t.state or "todo") in ALLOWED_STATES]


def _derive_blocked_tasks(tasks: list[Task]) -> list[Task]:
    """Derive blocked tasks (state == 'blocked')."""
    return [t for t in tasks if t.state == "blocked"]


def _derive_milestones(goals: list[Goal]) -> list[Milestone]:
    """Derive all milestones across all goals."""
    from janus.domain.planning import milestone_objs
    milestones: list[Milestone] = []
    for goal in goals:
        milestones.extend(milestone_objs(goal))
    return milestones


def _derive_projects(goals: list[Goal]) -> list[Project]:
    """Derive all projects across all goals."""
    from janus.domain.planning import project_objs
    projects: list[Project] = []
    for goal in goals:
        projects.extend(project_objs(goal))
    return projects


def _derive_measurement_requirements(goals: list[Goal]) -> list[dict]:
    """Derive measurement requirements from goals."""
    reqs: list[dict] = []
    for goal in goals:
        if goal.measurement_requirements:
            reqs.extend(goal.measurement_requirements)
    return reqs


def _derive_recent_activity(goals: list[Goal]) -> list[RecentActivityEntry]:
    """Derive recent activity entries from goals."""
    entries: list[RecentActivityEntry] = []
    for goal in goals:
        if goal.recent_activity:
            for entry_dict in goal.recent_activity:
                try:
                    entries.append(RecentActivityEntry.from_dict(entry_dict))
                except (KeyError, TypeError):
                    continue
    return entries


def _derive_research_artifacts(goals: list[Goal]) -> list[str]:
    """Derive research artifact titles linked to goals."""
    titles: set[str] = set()
    for goal in goals:
        if goal.research_artifact_titles:
            titles.update(goal.research_artifact_titles)
    return sorted(titles)


def _derive_stalled_goals(goals: list[Goal], tasks: list[Task]) -> list[Goal]:
    """Derive stalled goals based on health assessment.

    A goal is considered stalled if its health state is 'stalled'.
    This uses the existing goal_health service to assess each goal.
    """
    from janus.services.goal_health import assess_goal_health

    stalled: list[Goal] = []
    today = date.today()
    open_task_titles = {t.title for t in tasks}
    all_task_titles = open_task_titles.copy()
    for goal in goals:
        if goal.status != "active":
            continue
        try:
            assessment = assess_goal_health(
                goal, today,
                open_task_titles=open_task_titles,
                all_task_titles=all_task_titles,
            )
            if assessment and assessment.health_state == "stalled":
                stalled.append(goal)
        except Exception:
            continue
    return stalled


def _derive_neglected_goals(goals: list[Goal], tasks: list[Task]) -> list[Goal]:
    """Derive neglected goals based on health assessment.

    A goal is considered neglected if its health state is 'watch' or 'stalled'
    and it has insufficient strategic attention.
    """
    from janus.services.goal_health import assess_goal_health

    neglected: list[Goal] = []
    today = date.today()
    open_task_titles = {t.title for t in tasks}
    all_task_titles = open_task_titles.copy()
    for goal in goals:
        if goal.status != "active":
            continue
        try:
            assessment = assess_goal_health(
                goal, today,
                open_task_titles=open_task_titles,
                all_task_titles=all_task_titles,
            )
            if assessment and assessment.health_state in ("watch", "stalled"):
                neglected.append(goal)
        except Exception:
            continue
    return neglected


def _run_integrity_audit(
    goals: list[Goal],
    tasks: list[Task],
) -> list[GoalIntegrityIssue]:
    """Run goal integrity audit and return issues."""
    from janus.services.goal_integrity import audit_goal_integrity

    try:
        report = audit_goal_integrity(goals, tasks)
        return report.issues
    except Exception:
        return []


def _compute_strategic_summary(
    goals: list[Goal],
    tasks: list[Task],
    followups: list[FollowUp],
    decisions: list[Decision],
) -> StrategicSummary | None:
    """Compute strategic summary from current state.

    Returns None if the strategic summary cannot be computed.
    """
    try:
        from janus.services.strategic_summary import create_strategic_summary
        return create_strategic_summary(
            goals=goals,
            followups=followups,
            decisions=decisions,
        )
    except Exception:
        return None


def _compute_recommended_actions(
    goals: list[Goal],
    tasks: list[Task],
) -> list[RecommendedAction]:
    """Compute recommended actions from current state.

    Returns empty list if recommendations cannot be computed.
    """
    try:
        from janus.services.recommended_actions import (
            create_recommended_actions,
            identify_neglected_goals,
        )
        from janus.services.goal_health import assess_goal_health

        today = date.today()
        open_task_titles = {t.title for t in tasks}
        all_task_titles = open_task_titles.copy()
        assessments = []
        for goal in goals:
            if goal.status != "active":
                continue
            try:
                assessment = assess_goal_health(
                    goal, today,
                    open_task_titles=open_task_titles,
                    all_task_titles=all_task_titles,
                )
                if assessment:
                    assessments.append(assessment)
            except Exception:
                continue

        neglected = identify_neglected_goals(assessments, goals, open_task_titles, today)

        return create_recommended_actions(
            assessments,
            goals,
            open_task_titles=open_task_titles,
            today=today,
        )
    except Exception:
        return []


class PersonalStateBuilder:
    """Builder service for constructing the PersonalState aggregate.

    This is the repository/DAO layer for the personal state read model.
    It reads all source data files, builds domain models, derives computed
    views, runs integrity checks, and returns an immutable PersonalState.

    Usage:
        builder = PersonalStateBuilder()
        state = builder.build()
        print(state.active_goals)
        print(state.integrity_issues)
    """

    def __init__(self, project_root: Path | None = None):
        """Initialize the builder.

        Args:
            project_root: Optional override for the project root path.
                Defaults to the auto-detected project root.
        """
        self._project_root = project_root or PROJECT_ROOT

    def build(
        self,
        *,
        include_strategic_summary: bool = False,
        include_recommended_actions: bool = False,
        include_integrity_audit: bool = True,
    ) -> PersonalState:
        """Build the PersonalState aggregate from current data files.

        Args:
            include_strategic_summary: Whether to compute the strategic summary.
                This is expensive and should only be needed when the caller
                explicitly wants the strategic view.
            include_recommended_actions: Whether to compute recommended actions.
                This is expensive and should only be needed when the caller
                explicitly wants recommendations.
            include_integrity_audit: Whether to run the goal integrity audit.
                Defaults to True — integrity issues are a core part of the
                aggregate.

        Returns:
            An immutable PersonalState instance.
        """
        now = datetime.now().astimezone()

        # Load all source data.
        goals = _load_goals()
        tasks = _load_tasks()
        followups = _load_followups()
        inbox_items = _load_inbox_items()
        decisions = _load_decisions()
        workouts = _load_workouts()
        metric_snapshots = _load_metric_snapshots()

        # Derive computed views.
        active_goals = _derive_active_goals(goals)
        open_tasks = _derive_open_tasks(tasks)
        blocked_tasks = _derive_blocked_tasks(tasks)
        milestones = _derive_milestones(goals)
        projects = _derive_projects(goals)
        measurement_requirements = _derive_measurement_requirements(goals)
        recent_activity = _derive_recent_activity(goals)
        research_artifacts = _derive_research_artifacts(goals)

        # Derive health-based views.
        stalled_goals = _derive_stalled_goals(goals, tasks)
        neglected_goals = _derive_neglected_goals(goals, tasks)

        # Run integrity audit.
        integrity_issues: list[GoalIntegrityIssue] = []
        if include_integrity_audit:
            integrity_issues = _run_integrity_audit(goals, tasks)

        # Compute strategic summary if requested.
        strategic_summary: StrategicSummary | None = None
        if include_strategic_summary:
            strategic_summary = _compute_strategic_summary(
                goals, tasks, followups, decisions,
            )

        # Compute recommended actions if requested.
        recommended_actions: list[RecommendedAction] = []
        if include_recommended_actions:
            recommended_actions = _compute_recommended_actions(goals, tasks)

        # Compute data fingerprint.
        data_fingerprint = _compute_data_fingerprint()

        return PersonalState(
            generated_at=now,
            data_fingerprint=data_fingerprint,
            goals=goals,
            active_goals=active_goals,
            stalled_goals=stalled_goals,
            neglected_goals=neglected_goals,
            tasks=tasks,
            open_tasks=open_tasks,
            blocked_tasks=blocked_tasks,
            followups=followups,
            inbox_items=inbox_items,
            milestones=milestones,
            projects=projects,
            metric_snapshots=metric_snapshots,
            measurement_requirements=measurement_requirements,
            recent_activity=recent_activity,
            workouts=workouts,
            decisions=decisions,
            research_artifacts=research_artifacts,
            strategic_summary=strategic_summary,
            recommended_actions=recommended_actions,
            integrity_issues=integrity_issues,
        )


def build_personal_state(
    *,
    include_strategic_summary: bool = False,
    include_recommended_actions: bool = False,
    include_integrity_audit: bool = True,
) -> PersonalState:
    """Convenience function to build a PersonalState with default settings.

    This is the primary entry point for consumers who want a PersonalState
    without configuring the builder.

    Args:
        include_strategic_summary: Whether to compute the strategic summary.
        include_recommended_actions: Whether to compute recommended actions.
        include_integrity_audit: Whether to run the goal integrity audit.

    Returns:
        An immutable PersonalState instance.
    """
    builder = PersonalStateBuilder()
    return builder.build(
        include_strategic_summary=include_strategic_summary,
        include_recommended_actions=include_recommended_actions,
        include_integrity_audit=include_integrity_audit,
    )
