"""Milestone CRUD service for Janus goal execution planning.

Milestones are stored as list[dict] on the Goal (see Goal.milestones).
This service constructs real Milestone objects from those dicts, performs
CRUD operations, and persists changes via markdown_goals.update_goal.
"""

from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.integrations.markdown_goals import load_goals, update_goal


def _milestone_dict_from_obj(ms: Milestone) -> dict:
    """Serialize a Milestone to a plain dict for Goal persistence."""
    return {
        "title": ms.title,
        "goal_title": ms.goal_title,
        "description": ms.description,
        "deadline": ms.deadline,
        "status": ms.status,
        "related_tasks": list(ms.related_tasks),
        "order": ms.order,
    }


def _milestone_from_dict(data: dict) -> Milestone:
    """Construct a Milestone from a stored dict."""
    return Milestone(
        title=data["title"],
        goal_title=data.get("goal_title", ""),
        description=data.get("description", ""),
        deadline=data.get("deadline"),
        status=data.get("status", "open"),
        related_tasks=data.get("related_tasks"),
        order=data.get("order", 0),
    )


def get_milestones_for_goal(goal_title: str) -> list[Milestone]:
    """Return all milestones for a goal, ordered by ``order``.

    Raises ValueError if the goal does not exist.
    """
    goal = _get_goal_required(goal_title)
    mss = [_milestone_from_dict(d) for d in goal.milestones]
    mss.sort(key=lambda m: m.order)
    return mss


def _get_goal_required(goal_title: str) -> Goal:
    """Load a goal by title, raising ValueError if not found."""
    goals = load_goals()
    matches = [g for g in goals if g.title == goal_title]
    if not matches:
        raise ValueError(f"Goal not found: {goal_title!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple goals found with title {goal_title!r}")
    return matches[0]


def add_milestone_for_goal(
    goal_title: str,
    title: str,
    description: str = "",
    deadline: str | None = None,
    status: str = "open",
    related_tasks: list[str] | None = None,
) -> Milestone:
    """Create a new milestone for a goal with auto-assigned order.

    The new milestone's ``order`` is max(existing orders) + 1.
    Raises ValueError if the goal does not exist or a milestone with
    the same title already exists within the goal.
    """
    goal = _get_goal_required(goal_title)

    existing = get_milestones_for_goal(goal_title)
    if any(m.title == title for m in existing):
        raise ValueError(
            f"Milestone already exists: {title!r} in goal {goal_title!r}"
        )

    order = max([m.order for m in existing], default=-1) + 1

    ms = Milestone(
        title=title,
        goal_title=goal_title,
        description=description,
        deadline=deadline,
        status=status,
        related_tasks=related_tasks,
        order=order,
    )
    goal.milestones.append(_milestone_dict_from_obj(ms))
    update_goal(goal)
    return ms


def get_milestone(goal_title: str, milestone_title: str) -> Milestone:
    """Return a single milestone by title within a goal.

    Raises ValueError if the goal or milestone is not found.
    """
    existing = get_milestones_for_goal(goal_title)
    for m in existing:
        if m.title == milestone_title:
            return m
    raise ValueError(
        f"Milestone not found: {milestone_title!r} in goal {goal_title!r}"
    )


def update_milestone(goal_title: str, milestone_title: str, **kwargs) -> Milestone:
    """Update fields of an existing milestone.

    Valid kwargs: description, deadline, status, title, related_tasks,
    add_related_task, remove_related_task.
    Returns the updated Milestone. Raises ValueError if not found.
    """
    goal = _get_goal_required(goal_title)

    idx = _find_milestone_index(goal, milestone_title)
    ms_dict = goal.milestones[idx]

    for key, value in kwargs.items():
        if key == "add_related_task":
            tasks = ms_dict.get("related_tasks", [])
            if value not in tasks:
                tasks.append(value)
            ms_dict["related_tasks"] = tasks
        elif key == "remove_related_task":
            tasks = ms_dict.get("related_tasks", [])
            if value in tasks:
                tasks.remove(value)
            ms_dict["related_tasks"] = tasks
        else:
            ms_dict[key] = value

    # Reconstruct to re-run validaton via Milestone.__post_init__
    updated = _milestone_from_dict(ms_dict)
    goal.milestones[idx] = _milestone_dict_from_obj(updated)
    update_goal(goal)
    return updated


def _find_milestone_index(goal: Goal, milestone_title: str) -> int:
    """Return the list index of a milestone within goal.milestones."""
    for i, m in enumerate(goal.milestones):
        if m.get("title") == milestone_title:
            return i
    raise ValueError(
        f"Milestone not found: {milestone_title!r} in goal {goal.title!r}"
    )


def complete_milestone(goal_title: str, milestone_title: str) -> Milestone:
    """Mark a milestone as completed.

    Returns the updated Milestone. Raises ValueError if not found.
    """
    return update_milestone(
        goal_title, milestone_title, status="completed"
    )
