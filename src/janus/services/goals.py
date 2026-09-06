"""Goal CRUD service — add, get, update, complete.

Title is the persistence identity and is immutable in MVP.
No delete_goal — goals can be set to inactive.
"""

import logging

from janus._log import emit
from janus.models.goal import Goal
from janus.integrations.markdown_goals import GOALS_PATH, load_goals, save_goal, update_goal

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
                  set_research_artifacts.
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
        measurement_requirements=goal.measurement_requirements,
        research_artifact_titles=goal.research_artifact_titles,
    )

    update_goal(goal)

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
