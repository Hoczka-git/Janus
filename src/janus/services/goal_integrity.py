"""Goal Integrity Audit service for Janus.

Provides a deterministic, read-only health check of the relationships
between Goals, Tasks, metrics, and recent activity (spec §8, §7).

The audit logic is independent of the CLI and persistence layer. It
receives domain data and produces a ``GoalIntegrityReport``.

Design reference: ``docs/design/goal_integrity_audit.md``
"""
from datetime import datetime, timedelta

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.goal_integrity_report import (
    GoalIntegrityReport,
    GoalIntegrityIssue,
)


# ── Freshness threshold (spec §6.4, §6.3) ──────────────────────────────────────
# Reuse the existing INACTIVITY_WINDOW_DAYS constant from goal_health
# to keep a single source of truth for the "no recent activity" definition.
try:
    from janus.services.goal_health import INACTIVITY_WINDOW_DAYS
except ImportError:  # pragma: no cover — defensive
    INACTIVITY_WINDOW_DAYS = 30


# ── Issue codes (spec §6) ──────────────────────────────────────────────────────
GOAL_WITHOUT_TASKS = "GOAL_WITHOUT_TASKS"
UNKNOWN_GOAL_REFERENCE = "UNKNOWN_GOAL_REFERENCE"
INVALID_METRIC = "INVALID_METRIC"
STALE_ACTIVITY = "STALE_ACTIVITY"


def _is_valid_metric_config(goal: Goal) -> bool:
    """Return True if the goal's metric configuration is valid.

    Reuses the validation rules already encoded in ``compute_goal_progress``
    (spec §6.3): a metric goal is only valid when all five metric fields are
    present (metric_name, target_value, direction, start_value,
    current_value) and the values are consistent with ``direction``.
    """
    # No metric configured → not a metric goal → no INVALID_METRIC issue.
    if not goal.metric_name:
        return True

    # Partial metric config: metric_name present but required values missing.
    if (
        goal.target_value is None
        or goal.direction is None
        or goal.start_value is None
        or goal.current_value is None
    ):
        return False

    # Reuse the metric-progress validator to catch direction/value
    # inconsistencies (e.g. "increase" with target < start).
    from janus.services.goal_progress import _compute_metric_progress
    try:
        _compute_metric_progress(
            goal.start_value,
            goal.current_value,
            goal.target_value,
            goal.direction,
        )
    except (ValueError, TypeError):
        return False
    return True


def _goal_has_valid_metric(goal: Goal) -> bool:
    """Return True if the goal has a complete and valid metric configuration.

    A goal with ``metric_name`` set but incomplete fields is invalid
    (INVALID_METRIC). A goal with no metric_name at all is considered
    metric-valid (it uses the task-based path).
    """
    return _is_valid_metric_config(goal)


def _is_activity_stale(
    goal: Goal,
    now: datetime,
    metric_snapshots: list[MetricSnapshot],
) -> bool:
    """Return True if the goal has no recent relevant activity (spec §6.4).

    "An active goal has not received relevant activity within the configured
    freshness threshold." Relevant activity is any of:
    * a metric snapshot recorded for the goal's metric within the window;
    * a task-completion entry in ``recent_activity`` within the window.

    Only fires when the goal *has* some activity history but nothing within
    the window. A goal with no activity at all is left to ``GOAL_WITHOUT_TASKS``
    (spec §6.4 — stale implies activity once existed).
    """
    if goal.status != "active":
        return False

    window = goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS
    window_start = now - timedelta(days=window)

    # Collect every relevant activity timestamp that exists.
    timestamps: list[datetime] = []

    if goal.metric_name:
        relevant = [s for s in metric_snapshots if s.metric_name == goal.metric_name]
        timestamps.extend(s.timestamp for s in relevant)

    if goal.recent_activity:
        for entry in goal.recent_activity:
            completed_at = entry.get("completed_at")
            if not completed_at:
                continue
            try:
                if isinstance(completed_at, str):
                    entry_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                elif isinstance(completed_at, datetime):
                    entry_dt = completed_at
                else:
                    continue
                timestamps.append(entry_dt)
            except (ValueError, TypeError):
                continue

    # No activity history at all → not stale (covered by GOAL_WITHOUT_TASKS).
    if not timestamps:
        return False

    return not any(ts >= window_start for ts in timestamps)


def audit_goal_integrity(
    goals: list[Goal],
    tasks: list[Task],
    now: datetime | None = None,
    metric_snapshots: dict[str, list[MetricSnapshot]] | None = None,
) -> GoalIntegrityReport:
    """Run a deterministic Goal Integrity Audit (spec §8).

    Args:
        goals: All goals to inspect (active, completed, inactive).
        tasks: All open tasks (from ``load_tasks``).
        now: Explicit reference time for freshness checks (spec §7).
            Required for determinism — defaults to ``datetime.now()``.
        metric_snapshots: Optional pre-loaded snapshots keyed by goal title.
            If not provided, the service loads them per-goal.

    Returns:
        A complete ``GoalIntegrityReport``.

    The audit is strictly read-only: it does not modify goals, tasks, metrics,
    Kanban state, or execution state (spec §3, §3.2).
    """
    if now is None:
        now = datetime.now().astimezone()

    report = GoalIntegrityReport(
        goals_checked=len(goals),
        tasks_checked=len(tasks),
        evaluated_at=now,
    )

    # Build a set of existing goal titles for reference validation.
    goal_titles: set[str] = {g.title for g in goals}

    # Pre-load metric snapshots if not provided (spec §8 service boundary:
    # persistence loading stays outside the core audit, but we provide a
    # convenience path here so callers that pass pre-loaded data are
    # not penalized).
    if metric_snapshots is None:
        metric_snapshots = {}
        from janus.integrations.metric_history import get_metric_snapshots
        for g in goals:
            metric_snapshots[g.title] = get_metric_snapshots(g.title)

    # ── Check 1: Task → Goal references (UNKNOWN_GOAL_REFERENCE, spec §6.2)
    # ─────────────────────────────────────────────────────────────────────
    # Tasks reference goals via their ``extra_metadata`` field using the
    # ``goal: <title>`` or ``goal:<title>`` convention.
    task_goal_refs: set[str] = set()
    for task in tasks:
        refs = _extract_goal_refs(task)
        for ref in refs:
            task_goal_refs.add(ref)
            if ref not in goal_titles:
                report.issues.append(GoalIntegrityIssue(
                    code=UNKNOWN_GOAL_REFERENCE,
                    severity="error",
                    goal_id=ref,
                    task_id=task.title,
                    message=(
                        f"Task '{task.title}' references goal '{ref}' "
                        f"which does not exist."
                    ),
                    details={"task_id": task.title, "referenced_goal": ref},
                ))

    # ── Check 2-4: Per-goal checks ─────────────────────────────────────────
    for goal in goals:
        _check_goal_without_tasks(goal, tasks, report)
        _check_invalid_metric(goal, report)
        _check_stale_activity(goal, now, metric_snapshots, report)

    # ── Healthy checks (info-level, spec §5.3) ────────────────────────────────
    for goal in goals:
        if goal.status == "active":
            # GOAL_WITHOUT_TASKS would already be in issues; if not, it's healthy.
            if goal.related_tasks:
                report.healthy_checks.append(GoalIntegrityIssue(
                    code="GOAL_HAS_TASKS",
                    severity="info",
                    goal_id=goal.title,
                    message=(
                        f"Active goal '{goal.title}' has "
                        f"{len(goal.related_tasks)} related task(s)."
                    ),
                    details={"related_tasks": goal.related_tasks},
                ))
            # Valid metric reference
            if goal.metric_name and _goal_has_valid_metric(goal):
                report.healthy_checks.append(GoalIntegrityIssue(
                    code="GOAL_METRIC_VALID",
                    severity="info",
                    goal_id=goal.title,
                    message=f"Goal '{goal.title}' has valid metric configuration.",
                    details={"metric_name": goal.metric_name},
                ))

    return report


def _extract_goal_refs(task: Task) -> list[str]:
    """Extract goal title references from a task's metadata.

    Tasks reference goals via ``extra_metadata`` entries like ``goal: Title``
    or ``goal:Title``. Returns a list of referenced goal titles.
    """
    refs: list[str] = []
    if not task.extra_metadata:
        return refs
    for item in task.extra_metadata:
        if not isinstance(item, str):
            continue
        # Match "goal: Title" or "goal:Title"
        if item.startswith("goal:"):
            ref = item[len("goal:"):].strip()
            if ref:
                refs.append(ref)
        # Also support "goal" as a standalone with value on same token
        elif item.strip() == "goal" and len(refs) == 0:
            # "goal" alone with no title — skip, malformed
            continue
    return refs


def _check_goal_without_tasks(
    goal: Goal,
    tasks: list[Task],
    report: GoalIntegrityReport,
) -> None:
    """GOALS_WITHOUT_TASKS: active goal with no open/actionable tasks (§6.1).

    A goal with a valid metric configuration is considered actionable via its
    metric tracking path (see ``compute_goal_progress`` in goal_progress.py),
    so it is not flagged for lacking tasks.
    """
    if goal.status != "active":
        return

    # Metric-based goals (with a complete, valid metric config) track progress
    # via metric snapshots rather than tasks, so they are not flagged for
    # lacking tasks (spec §6.1 — "actionable" via metric path).
    if goal.metric_name and _is_valid_metric_config(goal):
        return

    # Task-based path: check goal.related_tasks and whether any open tasks
    # reference this goal.
    has_related = bool(goal.related_tasks)
    open_titles = {t.title for t in tasks}
    has_open_related = any(rt in open_titles for rt in goal.related_tasks)

    if not has_related and not has_open_related:
        report.issues.append(GoalIntegrityIssue(
            code=GOAL_WITHOUT_TASKS,
            severity="warning",
            goal_id=goal.title,
            message=(
                f"Active goal '{goal.title}' has no related open/actionable tasks."
            ),
            details={
                "related_tasks": list(goal.related_tasks),
                "open_task_count": len(open_titles),
            },
        ))


def _check_invalid_metric(goal: Goal, report: GoalIntegrityReport) -> None:
    """INVALID_METRIC: goal has an incomplete or invalid metric config (§6.3)."""
    # Only goals that declare a metric_name but are misconfigured are invalid.
    if goal.metric_name and not _goal_has_valid_metric(goal):
        report.issues.append(GoalIntegrityIssue(
            code=INVALID_METRIC,
            severity="error",
            goal_id=goal.title,
            message=(
                f"Goal '{goal.title}' has invalid metric configuration "
                f"(metric_name set but required fields missing or "
                f"inconsistent)."
            ),
            details={
                "metric_name": goal.metric_name,
                "has_target_value": goal.target_value is not None,
                "has_start_value": goal.start_value is not None,
                "has_current_value": goal.current_value is not None,
                "has_direction": goal.direction is not None,
            },
        ))


def _check_stale_activity(
    goal: Goal,
    now: datetime,
    metric_snapshots: dict[str, list[MetricSnapshot]],
    report: GoalIntegrityReport,
) -> None:
    """STALE_ACTIVITY: active goal with no relevant activity in the window (§6.4)."""
    if _is_activity_stale(goal, now, metric_snapshots.get(goal.title, [])):
        report.issues.append(GoalIntegrityIssue(
            code=STALE_ACTIVITY,
            severity="warning",
            goal_id=goal.title,
            message=(
                f"Active goal '{goal.title}' has had no metric update or "
                f"task completion within {goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS} days."
            ),
            details={
                "inactivity_window_days": goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS,
                "has_metric": goal.metric_name is not None,
            },
        ))
