"""Goal CRUD service — add, get, update, complete.

Title is the persistence identity and is immutable in MVP.
No delete_goal — goals can be set to inactive.
"""

from janus.models.goal import Goal
from janus.integrations.markdown_goals import load_goals, save_goal, update_goal


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
) -> Goal:
    """Validate and persist a new Goal.

    Title is the persistence identity — immutable in MVP.
    Raises ValueError on validation failure (via Goal constructor).
    """
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
    )
    save_goal(goal)
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
                  add_related_task, remove_related_task.
    Returns the updated Goal. Raises ValueError if goal not found or validation fails.
    """
    goal = get_goal(title)

    for key, value in kwargs.items():
        if key == "add_related_task":
            if value not in goal.related_tasks:
                goal.related_tasks.append(value)
        elif key == "remove_related_task":
            if value in goal.related_tasks:
                goal.related_tasks.remove(value)
        else:
            setattr(goal, key, value)

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
    )

    update_goal(goal)
    return goal


def complete_goal(title: str) -> Goal:
    """Mark a Goal as completed.

    Sets status='completed'. Returns the updated Goal.
    Raises ValueError if goal not found.
    """
    return update_goal_fields(title, status="completed")
