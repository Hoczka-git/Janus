"""Milestone CRUD service for Janus goal execution planning.

Milestones are stored as list[dict] on the Goal (see Goal.milestones).
This service constructs real Milestone objects from those dicts, performs
CRUD operations, and persists changes via markdown_goals.update_goal.

Task-to-milestone membership is NOT stored on the milestone — it is
derived dynamically (see services/next_action.py, ``derive_milestone_tasks``).
"""

from janus._log import emit
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.integrations.markdown_goals import load_goals, update_goal

import logging
logger = logging.getLogger(__name__)


def _milestone_dict_from_obj(ms: Milestone) -> dict:
    """Serialize a Milestone to a plain dict for Goal persistence."""
    return {
        "title": ms.title,
        "goal_title": ms.goal_title,
        "description": ms.description,
        "deadline": ms.deadline,
        "status": ms.status,
        "order": ms.order,
    }


def _milestone_from_dict(data: dict) -> Milestone:
    """Construct a Milestone from a stored dict.

    The ``related_tasks`` key is ignored if present (legacy data from the
    old permanent-assignment format). Membership is derived dynamically.
    """
    return Milestone(
        title=data["title"],
        goal_title=data.get("goal_title", ""),
        description=data.get("description", ""),
        deadline=data.get("deadline"),
        status=data.get("status", "open"),
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
) -> Milestone:
    """Create a new milestone for a goal with auto-assigned order.

    The new milestone's ``order`` is max(existing orders) + 1.
    Raises ValueError if the goal does not exist or a milestone with
    the same title already exists within the goal.

    Task membership is NOT stored — use ``derive_milestone_tasks`` to
    dynamically determine which tasks belong to this milestone at query time.
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

    Valid kwargs: description, deadline, status, title.

    Returns the updated Milestone. Raises ValueError if not found.
    """
    goal = _get_goal_required(goal_title)

    idx = _find_milestone_index(goal, milestone_title)
    ms_dict = goal.milestones[idx]

    for key, value in kwargs.items():
        ms_dict[key] = value

    # Reconstruct to re-run validation via Milestone.__post_init__
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


def start_milestone(goal_title: str, milestone_title: str) -> Milestone:
    """Mark a milestone as ``in_progress``.

    Returns the updated Milestone. Raises ValueError if not found.
    """
    return update_milestone(
        goal_title, milestone_title, status="in_progress"
    )


def skip_milestone(goal_title: str, milestone_title: str) -> Milestone:
    """Mark a milestone as ``skipped`` (intentionally abandoned).

    Returns the updated Milestone. Raises ValueError if not found.
    """
    return update_milestone(
        goal_title, milestone_title, status="skipped"
    )


def reopen_milestone(goal_title: str, milestone_title: str) -> Milestone:
    """Reopen a terminal milestone (completed or skipped) back to ``open``.

    Returns the updated Milestone. Raises ValueError if not found.
    """
    return update_milestone(
        goal_title, milestone_title, status="open"
    )


def update_milestone_status(
    title: str,
    completed_task_id: str,
    evidence: dict | None = None,
) -> Milestone:
    """Check milestone task completion threshold after a task completes.

    Called by the Hermes-side execution-feedback sync listener when a
    Kanban task that carries ``janus_domain: object: milestone``
    linkage completes.

    Uses ``derive_milestone_tasks`` to determine the milestone's task
    set (dynamically derived from ``goal.related_tasks``).  If all tasks
    in the milestone's set are now complete (i.e. the completed task
    was the last open one), the milestone is marked `completed` and an
    evidence entry is appended to ``goal.recent_activity``.

    The ``title`` here is the milestone title.  The goal title is
    resolved by searching all goals for a milestone with this title.

    Args:
        title: Milestone title (exact match within any goal).
        completed_task_id: Kanban task ID that completed.
        evidence: Evidence package dict.

    Returns:
        The (possibly updated) Milestone.

    Raises:
        ValueError: if the milestone is not found in any goal.
    """
    evidence = evidence or {}

    # Find the goal that contains this milestone by title
    goal = None
    goal_title_found = None
    ms_idx = None
    for g in load_goals():
        for i, m in enumerate(g.milestones):
            if m.get("title") == title:
                goal = g
                goal_title_found = g.title
                ms_idx = i
                break
        if goal is not None:
            break

    if goal is None:
        raise ValueError(f"Milestone not found: {title!r}")

    # Guard against None milestones (Goal.__post_init__ defaults to [])
    if goal.milestones is None:
        goal.milestones = []

    # Check current milestone status — if already completed, no-op
    ms_dict = goal.milestones[ms_idx]
    if ms_idx is None or ms_dict is None:
        raise ValueError(f"Milestone not found: {title!r}")
    if ms_dict.get("status") == "completed":
        # Already completed; just ensure evidence is recorded on goal
        _append_milestone_evidence(goal, completed_task_id, evidence)
        return _milestone_from_dict(ms_dict)

    # Derive the milestone's task set and check if all are now complete
    from janus.services.next_action import (
        _milestone_objs,
        derive_milestone_tasks,
    )
    from janus.integrations.markdown_tasks import load_tasks
    from janus.services.tasks import TASKS_PATH as _tasks_path

    milestone_objs = _milestone_objs(goal)
    milestone = None
    for m in milestone_objs:
        if m.title == title:
            milestone = m
            break

    if milestone is None:
        # Fallback: milestone dict exists but Milestone object construction failed
        return _milestone_from_dict(ms_dict)

    # Open tasks from the task file (use service-layer path for monkeypatching)
    open_tasks = load_tasks(_tasks_path)
    open_task_titles = {t.title for t in open_tasks}

    # The task just reported as completed should be treated as done for the
    # milestone threshold check — it may not yet be reflected in tasks.md
    # (complete_janus_task is a separate call the sync listener may or may
    # not have made before this one).  Exclude it from the open set.
    completed_task_title = evidence.get("summary")
    if completed_task_title:
        open_task_titles.discard(completed_task_title)

    # Derive which tasks belong to this milestone (only open ones).
    milestone_task_titles = derive_milestone_tasks(
        milestone, milestone_objs, goal, open_task_titles
    )

    # Check: are all tasks belonging to this milestone now complete?
    # ``derive_milestone_tasks`` returns only tasks still in the open set,
    # so if it returns empty, every task for this milestone is done.
    all_complete = len(milestone_task_titles) == 0

    if all_complete:
        ms_dict["status"] = "completed"
        goal.milestones[ms_idx] = ms_dict
        update_goal(goal)
        _append_milestone_evidence(goal, completed_task_id, evidence)
        emit(logger, "service.milestone.mutated",
             trace_id=None, span_id="service",
             operation="complete", milestone_title=title,
             goal_title=goal_title_found,
             message=f"Milestone '{title}' auto-completed (all tasks done)")
    else:
        # Milestone not yet complete; still record evidence for audit
        _append_milestone_evidence(goal, completed_task_id, evidence)
        emit(logger, "service.milestone.update",
             trace_id=None, span_id="service",
             operation="progress", milestone_title=title,
             goal_title=goal_title_found,
             message=f"Milestone '{title}' progress: task '{evidence.get('summary', completed_task_id)}' completed")

    return _milestone_from_dict(ms_dict)


def _append_milestone_evidence(goal: Goal, task_id: str, evidence: dict) -> None:
    """Append an evidence entry to a goal's recent_activity from a milestone
    completion sync.

    Idempotent: replaces any existing entry with the same ``task_id``.
    """
    if goal.recent_activity is None:
        goal.recent_activity = []

    entry = {
        "task_id": task_id,
        "summary": evidence.get("summary", ""),
        "completed_at": evidence.get("completed_at"),
        "changed_files": evidence.get("changed_files", []) or [],
        "tests_passed": evidence.get("tests_passed"),
        "pr_url": evidence.get("pr_url"),
    }

    goal.recent_activity = [
        e for e in goal.recent_activity
        if e.get("task_id") != task_id
    ]
    goal.recent_activity.append(entry)
    update_goal(goal)
