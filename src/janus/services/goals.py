"""Goal CRUD service — add, get, update, complete.

Title is the persistence identity and is immutable in MVP.
No delete_goal — goals can be set to inactive.
"""
from __future__ import annotations

import logging

from janus._log import emit
from janus.models.goal import Goal
from janus.integrations.markdown_goals import GOALS_PATH, load_goals, save_goal, update_goal
from janus.integrations.metric_history import append_metric_snapshot, MetricSnapshot

_VALID_FREQUENCIES = {"daily", "twice_weekly", "weekly", "weekends", "custom"}
_VALID_PREFERRED_TIMES = {"morning", "afternoon", "evening", "anytime"}


logger = logging.getLogger(__name__)


def add_goal(
    title: str,
    description: str = "",
    status: str = "active",
    deadline: str | None = None,
    metric_name: str | None = None,
    metric_unit: str | None = None,
    start_value: float | None = None,
    current_value: float | None = None,
    target_value: float | None = None,
    direction: str | None = None,
    related_tasks: list[str] | None = None,
    measurement_requirements: list[dict] | None = None,
    research_artifact_titles: list[str] | None = None,
    inactivity_window_days: int | None = None,
    skill_name: str | None = None,
) -> Goal:
    """Validate and persist a new Goal.

    Title is the persistence identity — immutable in MVP.
    Raises ValueError on validation failure (via Goal constructor)
    or if a goal with this title already exists.
    """
    if measurement_requirements is not None:
        for req in measurement_requirements:
            _validate_measurement_requirement(req)
    goal = Goal(
        title=title,
        description=description,
        status=status,
        deadline=deadline,
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        related_tasks=related_tasks,
        measurement_requirements=measurement_requirements,
        research_artifact_titles=research_artifact_titles,
        inactivity_window_days=inactivity_window_days,
        skill_name=skill_name,
    )
    # Check for duplicate title before saving
    existing = load_goals()
    if any(g.title == title for g in existing):
        raise ValueError(f"Goal already exists: {title!r}")
    save_goal(goal)

    emit(logger, "service.goal.mutated",
         trace_id=None, span_id="service",
         operation="add", goal_title=title,
         changes=None,
         message=f"Goal '{title}' added")

    return goal


def add_goal_via_ingest(title: str, **kwargs) -> "IngestResult":
    """Construct a GOAL_UPDATED ActivityRecord and route it through the
    canonical ADR-005 ingestion gate (``ingest_activities``).

    ``kwargs`` are passed through as the record's ``evidence`` dict, which
    the gateway's ``_dispatch_goal`` reads to populate goal fields.  This
    wrapper is used by CLI handlers so that writes pass through
    validation / normalization / deduplication in addition to atomic I/O.

    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    record = ActivityRecord(
        type=ActivityType.GOAL_CREATED,
        source="cli",
        timestamp=datetime.now(timezone.utc),
        goal_title=title,
        evidence=kwargs,
    )
    return ingest_activities([record])[0]


def update_goal_via_ingest(title: str, **kwargs) -> "IngestResult":
    """Construct a GOAL_UPDATED ActivityRecord and route it through the
    canonical ADR-005 ingestion gate (``ingest_activities``).

    ``kwargs`` mirror the field names accepted by ``update_goal_fields``
    (``description``, ``status``, ``metric_name``, etc.) and are passed
    through as the record's ``evidence`` dict, which
    ``_dispatch_goal`` reads to apply updates.

    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    record = ActivityRecord(
        type=ActivityType.GOAL_UPDATED,
        source="cli",
        timestamp=datetime.now(timezone.utc),
        goal_title=title,
        evidence=kwargs,
    )
    return ingest_activities([record])[0]


def get_goal(title: str) -> Goal:
    """Load a single Goal by exact title.

    Raises ValueError if not found or multiple found.
    """
    goals = load_goals()
    matches = [g for g in goals if g.title == title]
    if not matches:
        raise ValueError(f"Goal not found: {title!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple goals found with title {title!r}")
    return matches[0]


def update_goal_fields(title: str, **kwargs) -> Goal:
    """Update specific fields of an existing Goal.

    Title is NOT updatable (immutable in MVP).
    Valid kwargs: description, status, deadline, metric_name, metric_unit,
                  start_value, current_value, target_value, direction,
                  add_related_task, remove_related_task,
                  add_measurement_requirement, remove_measurement_requirement,
                  set_measurement_requirements,
                  add_research_artifact, remove_research_artifact,
                  set_research_artifacts,
                  inactivity_window_days,
                  skill_name.
    Returns the updated Goal. Raises ValueError if goal not found or validation fails.
    """
    goal = get_goal(title)

    changes: dict = {}
    for key, value in kwargs.items():
        if key == "add_related_task":
            if value not in goal.related_tasks:
                goal.related_tasks.append(value)
                changes.setdefault("related_tasks", []).append(value)
        elif key == "remove_related_task":
            if value in goal.related_tasks:
                goal.related_tasks.remove(value)
                changes.setdefault("related_tasks_removed", []).append(value)
        elif key == "add_measurement_requirement":
            _validate_measurement_requirement(value)
            goal.measurement_requirements.append(value)
        elif key == "remove_measurement_requirement":
            goal.measurement_requirements = [
                r for r in goal.measurement_requirements if r.get("metric") != value
            ]
        elif key == "set_measurement_requirements":
            for req in value:
                _validate_measurement_requirement(req)
            goal.measurement_requirements = list(value)
        elif key == "add_research_artifact":
            if value not in goal.research_artifact_titles:
                goal.research_artifact_titles.append(value)
                changes.setdefault("research_artifact_titles", []).append(value)
        elif key == "remove_research_artifact":
            if value in goal.research_artifact_titles:
                goal.research_artifact_titles.remove(value)
                changes.setdefault("research_artifact_titles_removed", []).append(value)
        elif key == "set_research_artifacts":
            goal.research_artifact_titles = list(value)
            changes["research_artifact_titles"] = list(value)
        elif key == "add_decision_number":
            if value not in goal.decision_numbers:
                goal.decision_numbers.append(value)
                changes.setdefault("decision_numbers", []).append(value)
        elif key == "add_followup_id":
            if value not in goal.followup_ids:
                goal.followup_ids.append(value)
                changes.setdefault("followup_ids", []).append(value)
        else:
            old_val = getattr(goal, key, None)
            setattr(goal, key, value)
            changes[key] = value

    # Re-validate via Goal constructor (runs __post_init__)
    goal = Goal(
        title=goal.title,
        description=goal.description,
        status=goal.status,
        deadline=goal.deadline,
        metric_name=goal.metric_name,
        metric_unit=goal.metric_unit,
        start_value=goal.start_value,
        current_value=goal.current_value,
        target_value=goal.target_value,
        direction=goal.direction,
        related_tasks=goal.related_tasks,
        milestones=goal.milestones,
        projects=goal.projects,
        measurement_requirements=goal.measurement_requirements,
        research_artifact_titles=goal.research_artifact_titles,
        decision_numbers=goal.decision_numbers,
        followup_ids=goal.followup_ids,
        inactivity_window_days=goal.inactivity_window_days,
        recent_activity=goal.recent_activity,
        skill_name=goal.skill_name,
        skill_evidence=goal.skill_evidence,
    )

    update_goal(goal)

    # Record a metric snapshot when current_value is updated and the goal
    # has a metric configured (design §7.3 / §12.4).
    if "current_value" in changes and goal.metric_name is not None:
        from datetime import datetime
        snapshot = MetricSnapshot(
            timestamp=datetime.now().astimezone(),
            goal_title=goal.title,
            metric_name=goal.metric_name,
            value=float(goal.current_value),
            source="manual",
        )
        append_metric_snapshot(snapshot)
        emit(logger, "service.goal.snapshot_created",
             trace_id=None, span_id="service",
             operation="update", goal_title=title,
             metric_name=goal.metric_name,
             message=f"Metric snapshot recorded for goal '{title}'")

    if changes:
        emit(logger, "service.goal.mutated",
             trace_id=None, span_id="service",
             operation="update", goal_title=title,
             changes=changes,
             message=f"Goal '{title}' updated")

    return goal


def complete_goal(title: str) -> Goal:
    """Mark a Goal as completed.

    Sets status='completed'. Returns the updated Goal.
    Raises ValueError if goal not found.
    """
    return update_goal_fields(title, status="completed")


def complete_goal_via_ingest(title: str) -> "IngestResult":
    """Construct a GOAL_COMPLETED ActivityRecord and route it through the
    canonical ADR-005 ingestion gate (``ingest_activities``).

    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    record = ActivityRecord(
        type=ActivityType.GOAL_COMPLETED,
        source="cli",
        timestamp=datetime.now(timezone.utc),
        goal_title=title,
        evidence={},
    )
    return ingest_activities([record])[0]


def update_goal_progress(
    title: str,
    completed_task_id: str,
    completed_task_title: str,
    evidence: dict | None = None,
    skill_name: str | None = None,
) -> Goal:
    """Record completion evidence on a Goal and bump its progress.

    Called by the Hermes-side execution-feedback sync listener when a
    Kanban task that carries ``janus_domain: object: goal`` linkage
    completes.

    Appends an activity entry to ``goal.recent_activity`` and persists
    the goal.  If the evidence package indicates the goal's metric
    ``current_value`` should advance (via ``evidence.current_value``),
    the metric is updated too.

    If ``skill_name`` is provided and matches ``goal.skill_name`` (or the
    goal has no skill set yet), the evidence entry is also appended to
    ``goal.skill_evidence``.  If the skill_name does not match the goal's
    existing skill, evidence goes to ``recent_activity`` only (a warning
    is logged).

    This operation is idempotent: if an activity entry with the same
    ``task_id`` already exists, it is replaced rather than duplicated.

    Args:
        title: Goal title (exact match).
        completed_task_id: Kanban task ID that completed.
        completed_task_title: Human-readable summary of the task.
        evidence: Evidence package dict with keys ``task_id``,
            ``summary``, ``completed_at``, ``changed_files``,
            ``tests_passed``, ``pr_url``.  May also include
            ``current_value`` to advance the goal's metric (legacy,
            deprecated in favor of ``metric_updates``), or
            ``metric_updates`` — a list of ``{"metric_name", "value",
            "unit"}`` dicts for declarative multi-metric advancement.
        skill_name: Optional skill label to associate with this evidence.

    Returns:
        The updated Goal.

    Raises:
        ValueError: if the goal is not found.
    """
    goal = get_goal(title)
    if goal.recent_activity is None:
        goal.recent_activity = []

    # Build the activity entry from evidence
    entry = {
        "task_id": completed_task_id,
        "summary": completed_task_title,
        "completed_at": (evidence or {}).get("completed_at"),
        "changed_files": (evidence or {}).get("changed_files", []) or [],
        "tests_passed": (evidence or {}).get("tests_passed"),
        "pr_url": (evidence or {}).get("pr_url"),
    }

    # Idempotency: replace existing entry for this task_id
    goal.recent_activity = [
        e for e in goal.recent_activity
        if e.get("task_id") != completed_task_id
    ]
    goal.recent_activity.append(entry)

    # Skill evidence: if skill_name matches the goal's skill (or the goal
    # has no skill yet), append the entry to skill_evidence too.
    # The entry shape matches recent_activity entries (design §4.1).
    if skill_name:
        if goal.skill_name is None:
            goal.skill_name = skill_name.strip()
        if goal.skill_evidence is None:
            goal.skill_evidence = []
        if goal.skill_name == skill_name.strip():
            # Replace existing skill_evidence entry for this task_id (idempotent)
            goal.skill_evidence = [
                e for e in goal.skill_evidence
                if e.get("task_id") != completed_task_id
            ]
            goal.skill_evidence.append(entry)
        else:
            # Skill mismatch — evidence goes to recent_activity only
            logger.warning(
                "skill_name %r does not match goal %r's skill %r; "
                "evidence recorded in recent_activity only",
                skill_name, goal.title, goal.skill_name,
            )

    # Optionally advance the metric.  The evidence dict may carry a
    # declarative ``metric_updates`` list (design §6.2), where each entry is
    # a dict with ``metric_name``, ``value`` and optional ``unit``.  This
    # supports multi-metric goals and supersedes the single-value
    # ``current_value`` legacy field (kept for one migration cycle).
    current_val = (evidence or {}).get("current_value")
    metric_updates = (evidence or {}).get("metric_updates")
    if metric_updates:
        for mu in metric_updates:
            if not isinstance(mu, dict):
                continue
            mu_name = mu.get("metric_name")
            mu_val = mu.get("value")
            mu_unit = mu.get("unit")
            if mu_name == goal.metric_name and mu_val is not None:
                goal.current_value = float(mu_val)
                if mu_unit and not goal.metric_unit:
                    goal.metric_unit = mu_unit
    elif current_val is not None and goal.metric_name is not None:
        # Legacy single-value path (deprecated, one migration cycle).
        goal.current_value = float(current_val)

    update_goal(goal)

    emit(logger, "service.goal.mutated",
         trace_id=None, span_id="service",
         operation="update_goal_progress", goal_title=title,
         task_id=completed_task_id,
         message=f"Goal progress updated from task '{completed_task_title}'")

    return goal


def _validate_measurement_requirement(req: dict) -> None:
    """Validate a measurement requirement dict.

    Raises ValueError with a descriptive message if invalid.
    """
    if not isinstance(req, dict):
        raise ValueError("measurement requirement must be a dict")
    metric = req.get("metric")
    if not metric or not metric.strip():
        raise ValueError("measurement requirement must have a non-empty 'metric'")
    frequency = req.get("frequency")
    if frequency is not None:
        if frequency not in _VALID_FREQUENCIES:
            raise ValueError(
                f"Invalid frequency: {frequency!r}. "
                f"Allowed: {_VALID_FREQUENCIES}"
            )
    if frequency == "custom":
        interval = req.get("interval_days")
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError(
                "frequency='custom' requires a positive integer 'interval_days'"
            )
    unit = req.get("unit")
    if unit is not None and not unit.strip():
        raise ValueError("'unit' must be a non-empty string if provided")
    preferred_time = req.get("preferred_time")
    if preferred_time is not None:
        if preferred_time not in _VALID_PREFERRED_TIMES:
            raise ValueError(
                f"Invalid preferred_time: {preferred_time!r}. "
                f"Allowed: {_VALID_PREFERRED_TIMES}"
            )
