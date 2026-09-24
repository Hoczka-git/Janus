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

# ── Extended issue codes (orphan + invalid related_task detection) ─────────────
# These cover detection scenarios identified in the schema research (§4.8)
# and the orphan/invalid-related_task task spec:
#   * Tasks that are not reachable from any goal (orphan tasks).
#   * Goal.related_tasks entries that point to non-existent or deleted tasks.
#   * Bidirectional reference counts that don't match (consistency violation).
#   * Circular goal→task→goal →task→goal references (consistency violation).
ORPHANED_TASK = "ORPHANED_TASK"
INVALID_RELATED_TASK = "INVALID_RELATED_TASK"
RELATIONSHIP_COUNT_MISMATCH = "RELATIONSHIP_COUNT_MISMATCH"
CIRCULAR_REFERENCE = "CIRCULAR_REFERENCE"


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
    task_to_goals: dict[str, list[str]] = {}  # task_title → [goal_titles referenced]
    for task in tasks:
        refs = _extract_goal_refs(task)
        if refs:
            task_to_goals[task.title] = refs
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

    # ── Check 5: Orphan tasks — tasks not referenced by any goal ───────────
    # An orphan task is an open task that has no ``goal:`` reference in its
    # extra_metadata and is not listed in any goal's ``related_tasks``.
    # Such tasks are unreachable from the goal graph and may indicate lost
    # work or accidental omission of the linkage (research §4.4, §4.8).
    _check_orphan_tasks(goals, tasks, report)

    # ── Check 6: Invalid related_task references in goals ─────────────────
    # Each entry in ``goal.related_tasks`` should correspond to an open task.
    # Entries pointing to non-existent or already-completed tasks are invalid.
    open_task_titles: set[str] = {t.title for t in tasks}
    _check_invalid_related_tasks(goals, open_task_titles, report)

    # ── Check 7: Bidirectional reference count consistency ─────────────────
    # For each goal, the number of tasks referencing it (via ``goal:`` metadata)
    # should be consistent with the goal's ``related_tasks`` list. A mismatch
    # indicates the bidirectional link is out of sync (research §4.2).
    # Build reverse index: goal_title → set of task titles that reference it.
    goal_to_task_refs: dict[str, set[str]] = {}
    for task in tasks:
        refs = task_to_goals.get(task.title, [])
        for ref in refs:
            goal_to_task_refs.setdefault(ref, set()).add(task.title)
    _check_relationship_count_mismatch(goals, goal_to_task_refs, report)

    # ── Check 8: Circular references ───────────────────────────────────────
    # Detect circular goal→task→goal→task→goal chains. A circular reference
    # exists when a task references goal A, and goal A's related_tasks includes
    # a task that references goal A again — indicating a self-referential loop
    # that cannot resolve. We also check for goal-to-goal cycles indirectly
    # through the task graph.
    _check_circular_references(goals, tasks, task_to_goals, report)

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


# ── Extended checks: orphans, invalid refs, consistency ─────────────────────────

def _check_orphan_tasks(
    goals: list[Goal],
    tasks: list[Task],
    report: GoalIntegrityReport,
) -> None:
    """ORPHANED_TASK: an open task with no parent goal (spec ext §4.4, §4.8).

    A task is an orphan when:
    * It has no ``goal:`` reference in its ``extra_metadata``, AND
    * Its title does not appear in any goal's ``related_tasks`` list.

    Orphan tasks are unreachable from the goal graph. Completed tasks are
    not flagged — a completed task without a goal link may be standalone
    work (e.g. a house chore).

    Severity: ``warning`` — the task may be intentionally standalone, so we
    surface it for review rather than treating it as an error.
    """
    goal_related_task_titles: set[str] = set()
    for g in goals:
        goal_related_task_titles.update(g.related_tasks)

    for task in tasks:
        # Skip tasks that already have a goal: reference (those are validated
        # for existence by Check 1 / UNKNOWN_GOAL_REFERENCE).
        refs = _extract_goal_refs(task)
        if refs:
            continue
        # Skip tasks that are listed in any goal's related_tasks.
        if task.title in goal_related_task_titles:
            continue
        report.issues.append(GoalIntegrityIssue(
            code=ORPHANED_TASK,
            severity="warning",
            goal_id=None,
            task_id=task.title,
            message=(
                f"Task '{task.title}' has no link to any goal and does not "
                f"appear in any goal's related_tasks."
            ),
            details={
                "task_id": task.title,
                "goals_checked": report.goals_checked,
            },
        ))


def _check_invalid_related_tasks(
    goals: list[Goal],
    open_task_titles: set[str],
    report: GoalIntegrityReport,
) -> None:
    """INVALID_RELATED_TASK: goal.related_tasks entry with no matching open task.

    Each entry in ``goal.related_tasks`` should point to an open task that
    exists in ``data/tasks.md``. Entries pointing to non-existent tasks or
    to tasks already marked completed (``- [x]``) are invalid — they indicate
    stale or deleted task references (research §4.2, §4.8).

    Severity: ``error`` — a goal claiming a related task that doesn't exist
    is a structural inconsistency.
    """
    for goal in goals:
        if not goal.related_tasks:
            continue
        for rt in goal.related_tasks:
            if rt not in open_task_titles:
                report.issues.append(GoalIntegrityIssue(
                    code=INVALID_RELATED_TASK,
                    severity="error",
                    goal_id=goal.title,
                    task_id=rt,
                    message=(
                        f"Goal '{goal.title}' references related_task '{rt}' "
                        "which does not match any open task (it may have been "
                        "deleted, renamed, or already completed)."
                    ),
                    details={
                        "goal_id": goal.title,
                        "related_task": rt,
                        "open_task_count": len(open_task_titles),
                    },
                ))


def _check_relationship_count_mismatch(
    goals: list[Goal],
    goal_to_task_refs: dict[str, set[str]],
    report: GoalIntegrityReport,
) -> None:
    """RELATIONSHIP_COUNT_MISMATCH: bidirectional link counts disagree.

    The forward link (``goal.related_tasks``) and the reverse link
    (``task.extra_metadata: goal: <title>``) should be consistent. A mismatch
    indicates the bidirectional link is out of sync (research §4.2 — no
    bidirectional sync mechanism exists).

    The forward link (``goal.related_tasks``) is the canonical source of truth.
    The reverse link (``goal:`` metadata on tasks) is advisory and may be
    absent for tasks that are linked only via the forward direction. We only
    flag mismatches when reverse references *exist* but disagree with the
    forward references:

    * A task in ``goal.related_tasks`` has a ``goal:`` ref to a *different*
      goal (forward says A, reverse says B).
    * A task has a ``goal:`` ref to a goal that does NOT list it in
      ``related_tasks`` (reverse-only link with no forward counterpart).
    * A goal's ``related_tasks`` count doesn't match the count of tasks
      referencing it when both sides are populated (count mismatch).

    Severity: ``warning`` — may indicate a recently broken link. The audit is
    read-only so we report rather than auto-fix.
    """
    # Build a map of task_title -> set of goals it references (reverse links).
    for goal in goals:
        forward_tasks = set(goal.related_tasks)
        reverse_tasks = goal_to_task_refs.get(goal.title, set())

        # Reverse-only: task references this goal but is not in related_tasks.
        reverse_only = reverse_tasks - forward_tasks
        for t in sorted(reverse_only):
            report.issues.append(GoalIntegrityIssue(
                code=RELATIONSHIP_COUNT_MISMATCH,
                severity="warning",
                goal_id=goal.title,
                task_id=t,
                message=(
                    f"Task '{t}' references goal '{goal.title}' via "
                    f"'goal:' metadata but the goal does not list it in "
                    f"related_tasks."
                ),
                details={
                    "goal_id": goal.title,
                    "task_id": t,
                    "forward_count": len(forward_tasks),
                    "reverse_count": len(reverse_tasks),
                },
            ))

        # Forward-only count mismatch: when the goal has a non-empty
        # related_tasks list AND at least one task references the goal via
        # ``goal:`` metadata, but the counts don't match. This catches the
        # case where the forward and reverse links have diverged in size.
        if forward_tasks and reverse_tasks and forward_tasks != reverse_tasks:
            # Only report the count mismatch (not individual task-level issues,
            # which are already covered above for reverse-only tasks).
            report.issues.append(GoalIntegrityIssue(
                code=RELATIONSHIP_COUNT_MISMATCH,
                severity="warning",
                goal_id=goal.title,
                task_id=None,
                message=(
                    f"Goal '{goal.title}' has {len(forward_tasks)} task(s) in "
                    f"related_tasks but {len(reverse_tasks)} task(s) reference "
                    f"it via 'goal:' metadata — counts do not match."
                ),
                details={
                    "goal_id": goal.title,
                    "forward_count": len(forward_tasks),
                    "reverse_count": len(reverse_tasks),
                },
            ))


def _check_circular_references(
    goals: list[Goal],
    tasks: list[Task],
    task_to_goals: dict[str, list[str]],
    report: GoalIntegrityReport,
) -> None:
    """CIRCULAR_REFERENCE: goal↔task mutual reference loops (spec ext).

    Detects cycles in the goal→task→goal relationship graph. A circular
    reference occurs when:
    * A goal lists a task in ``related_tasks``, AND
    * That task references the goal back via ``goal:`` metadata, AND
    * The task also references another goal that in turn references this task.

    More concretely, we build a bipartite graph of goals and tasks and detect
    any cycle of length >= 4 (goal → task → goal → task → ... → goal). The
    simplest and most common case is a 2-cycle: goal A references task T,
    and task T references goal A — which is actually the *expected* valid
    pattern. So we do NOT flag simple goal↔task mutual links.

    We flag only true cycles: goal A → task T1 → goal B → task T2 → goal A
    (where A != B). This indicates a task is shared across multiple goals in
    a way that creates an unresolved dependency loop.

    Severity: ``error`` — circular references in the goal graph can cause
    infinite loops in planning and execution.
    """
    # Build adjacency: goal_title → set of task titles it references
    goal_edges: dict[str, set[str]] = {}
    for g in goals:
        goal_edges.setdefault(g.title, set()).update(g.related_tasks)

    # Build adjacency: task_title → set of goal titles it references
    task_edges: dict[str, set[str]] = {}
    for task in tasks:
        refs = task_to_goals.get(task.title, [])
        if refs:
            task_edges.setdefault(task.title, set()).update(refs)

    all_goal_titles = set(goal_edges.keys())

    def _find_cycle_from(start_goal: str) -> list[str] | None:
        """DFS from start_goal looking for a cycle back to start_goal.

        Path alternates goal->task->goal->task. We only flag cycles where the
        path returns to the start goal through a *different* goal (i.e. a
        cycle involving >= 2 distinct goals).
        """
        visited_goals: set[str] = set()
        visited_tasks: set[str] = set()

        def _dfs(current_goal: str, path: list[str]) -> list[str] | None:
            if current_goal in visited_goals:
                return None
            visited_goals.add(current_goal)
            path.append(current_goal)
            for task in goal_edges.get(current_goal, set()):
                if task in visited_tasks:
                    continue
                visited_tasks.add(task)
                path.append(task)
                for next_goal in task_edges.get(task, set()):
                    if next_goal not in all_goal_titles:
                        continue
                    if next_goal == start_goal and len(path) >= 4:
                        # Found a cycle back to start through >= 2 goals.
                        path.append(next_goal)
                        return list(path)
                    if next_goal not in visited_goals:
                        result = _dfs(next_goal, path)
                        if result is not None:
                            return result
                path.pop()  # remove task from path on backtrack
            path.pop()  # remove goal from path on backtrack
            return None

        return _dfs(start_goal, [])

    seen_cycle_goals: set[str] = set()
    for goal_title in all_goal_titles:
        if goal_title in seen_cycle_goals:
            continue
        cycle = _find_cycle_from(goal_title)
        if cycle is not None:
            # Record all goals in the cycle to avoid duplicate reports.
            cycle_goals = {n for n in cycle if n in all_goal_titles}
            seen_cycle_goals.update(cycle_goals)
            cycle_str = " -> ".join(cycle)
            report.issues.append(GoalIntegrityIssue(
                code=CIRCULAR_REFERENCE,
                severity="error",
                goal_id=goal_title,
                task_id=None,
                message=(
                    f"Circular reference detected in goal/task graph: {cycle_str}. "
                    f"This cycle involves {len(cycle_goals)} goal(s) and may "
                    f"cause infinite loops in planning."
                ),
                details={
                    "cycle": cycle,
                    "goals_in_cycle": sorted(cycle_goals),
                    "length": len(cycle),
                },
            ))

