"""Goal progress calculation — centralized, single source of truth.

All goal progress logic lives here. Weekly Review and CLI delegate to this
module. No other module duplicates metric-vs-task priority logic.
"""

from janus.models.goal import Goal


def compute_goal_progress(
    goal: Goal,
    completed_task_titles: set[str] | None = None,
) -> float | None:
    """Compute progress for a Goal.

    Priority (when goal.status == "active"):
    1. Metric path: if metric_name, target_value, direction, start_value,
       current_value all present → compute_metric_progress()
    2. Task-based path: elif related_tasks non-empty AND
       completed_task_titles is not None → compute_task_based_progress()
    3. Otherwise → None

    Returns None for: completed/inactive goals, missing metric fields,
    no tasks and no completed_task_titles provided, invalid metric config.
    """
    if goal.status != "active":
        return None

    # Metric path — has priority
    if (goal.metric_name and goal.target_value is not None
            and goal.direction and goal.start_value is not None
            and goal.current_value is not None):
        try:
            return _compute_metric_progress(
                goal.start_value,
                goal.current_value,
                goal.target_value,
                goal.direction,
            )
        except ValueError:
            return None  # invalid metric config → no progress

    # Task-based path
    if goal.related_tasks and completed_task_titles is not None:
        completed_count = sum(
            1 for rt in goal.related_tasks if rt in completed_task_titles
        )
        return _compute_task_based_progress(goal.related_tasks, completed_count)

    return None


def _compute_metric_progress(
    start_value: float,
    current_value: float,
    target_value: float,
    direction: str,
) -> float:
    """Low-level metric progress. Raises ValueError on invalid config.

    Handles start_value == target_value BEFORE direction validation
    (degenerate maintain-at-X goal).
    """
    if direction not in ("increase", "decrease"):
        raise ValueError(
            f"Invalid direction: {direction!r}. Allowed: increase, decrease"
        )

    # Degenerate maintain-at-X goal — equality check FIRST
    if start_value == target_value:
        return 100.0 if current_value == target_value else 0.0

    if direction == "increase":
        if target_value < start_value:
            raise ValueError(
                f"Invalid increase goal: target ({target_value}) must be "
                f"greater than start ({start_value})"
            )
        if current_value <= start_value:
            return 0.0
        if current_value >= target_value:
            return 100.0
        return (current_value - start_value) / (target_value - start_value) * 100.0

    # direction == "decrease"
    if target_value > start_value:
        raise ValueError(
            f"Invalid decrease goal: target ({target_value}) must be "
            f"less than start ({start_value})"
        )
    if current_value >= start_value:
        return 0.0
    if current_value <= target_value:
        return 100.0
    return (start_value - current_value) / (start_value - target_value) * 100.0


def _compute_task_based_progress(
    related_tasks: list[str],
    completed_count: int,
) -> float:
    """Task-based progress percentage.

    Validates: related_tasks non-empty, 0 <= completed_count <= len(related_tasks).
    Raises ValueError if validation fails.
    """
    if not related_tasks:
        raise ValueError("related_tasks must be non-empty")
    total = len(related_tasks)
    if not (0 <= completed_count <= total):
        raise ValueError(
            f"completed_count ({completed_count}) must be between 0 and "
            f"len(related_tasks) ({total})"
        )
    return (completed_count / total) * 100.0
