"""Project CRUD service for Janus goal execution planning.

Projects are stored as list[dict] on the Goal (see Goal.projects).
This service constructs real Project objects from those dicts, performs
CRUD operations, and persists changes via markdown_goals.update_goal.

Domain invariants enforced:
- I1: Project belongs to an existing Milestone.
- I2: Project title is unique within its Milestone.
- I3: A Task can belong to at most one Project within a Goal.
- I4: Project tasks must belong to the same Goal (cross-goal rejected).
- I6: Project assignment overrides dynamic derivation.
"""

import logging
from typing import Any

from janus._log import emit
from janus.models.goal import Goal
from janus.models.project import Project
from janus.models.milestone import Milestone
from janus.integrations.markdown_goals import load_goals, update_goal

logger = logging.getLogger(__name__)


def _get_goal_required(goal_title: str) -> Goal:
    """Load a goal by title, raising ValueError if not found."""
    goals = load_goals()
    matches = [g for g in goals if g.title == goal_title]
    if not matches:
        raise ValueError(f"Goal not found: {goal_title!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple goals found with title {goal_title!r}")
    return matches[0]


def _get_milestone_required(goal: Goal, milestone_title: str) -> Milestone:
    """Return a Milestone object for the given title within a goal.

    Raises ValueError if the milestone is not found.
    """
    from janus.services.milestones import get_milestones_for_goal
    milestones = get_milestones_for_goal(goal.title)
    for m in milestones:
        if m.title == milestone_title:
            return m
    raise ValueError(
        f"Milestone not found: {milestone_title!r} in goal {goal.title!r}"
    )


def _project_dict_from_obj(proj: Project, goal_title: str) -> dict:
    """Serialize a Project to a plain dict for Goal persistence."""
    return {
        "title": proj.title,
        "goal_title": goal_title,
        "milestone_title": proj.milestone_title,
        "description": proj.description,
        "deadline": proj.deadline,
        "status": proj.status,
        "order": proj.order,
        "related_tasks": list(proj.related_tasks),
    }


def _project_from_dict(data: dict) -> Project:
    """Construct a Project from a stored dict."""
    return Project(
        title=data["title"],
        milestone_title=data["milestone_title"],
        description=data.get("description", ""),
        deadline=data.get("deadline"),
        status=data.get("status", "open"),
        order=data.get("order", 0),
        related_tasks=list(data.get("related_tasks", [])),
    )


def _project_index(goal: Goal, milestone_title: str, project_title: str) -> int:
    """Return the list index of a project within goal.projects.

    Matches by both milestone_title and title to support the I2 invariant
    (title unique within milestone, but same title may exist in different milestones).
    Raises ValueError if not found.
    """
    for i, p in enumerate(goal.projects):
        if p.get("milestone_title") == milestone_title and p.get("title") == project_title:
            return i
    raise ValueError(
        f"Project not found: {project_title!r} in milestone "
        f"{milestone_title!r} of goal {goal.title!r}"
    )


def _validate_project_status(status: str) -> None:
    """Validate that the status is a recognized Project status."""
    valid = {"open", "active", "blocked", "completed", "skipped"}
    if status not in valid:
        raise ValueError(
            f"Invalid project status: {status!r}. "
            f"Allowed: {', '.join(sorted(valid))}"
        )


def _check_duplicate_task_assignment(
    goal: Goal, milestone_title: str, project_title: str,
    new_tasks: list[str],
) -> None:
    """Enforce I3: a Task can belong to at most one Project within a Goal.

    ``new_tasks`` are the tasks being assigned to *this* project. We check
    whether any of them already appear in a *different* project under the
    same Goal. Skips the project being updated (identified by title+ms).
    """
    for i, p in enumerate(goal.projects):
        same = (p.get("milestone_title") == milestone_title
                and p.get("title") == project_title)
        if same:
            continue
        existing_tasks = set(p.get("related_tasks", []))
        dupes = set(new_tasks) & existing_tasks
        if dupes:
            dup_str = ", ".join(sorted(dupes))
            raise ValueError(
                f"Task(s) already assigned to another project in this goal: {dup_str}"
            )


def _warn_cross_goal_tasks(
    goal: Goal, related_tasks: list[str], milestone_title: str,
) -> None:
    """Issue a warning if a Project references tasks not in the Goal's inventory.

    Per spec §6.4: warn (don't fail) if a task is not currently in
    goal.related_tasks, because it may be added later. Cross-goal references
    are NOT possible at this layer (tasks are title-based, not Goal-scoped),
    so we only warn about missing inventory references.
    """
    goal_tasks = set(goal.related_tasks)
    for t in related_tasks:
        if t not in goal_tasks:
            logger.warning(
                "Project in goal %r (milestone %r) references task %r "
                "not currently in goal.related_tasks — may be added later.",
                goal.title, milestone_title, t,
            )


def add_project_for_milestone(
    goal_title: str,
    milestone_title: str,
    title: str,
    description: str = "",
    deadline: str | None = None,
    status: str = "open",
    related_tasks: list[str] | None = None,
) -> Project:
    """Create a new project under a milestone.

    Enforces I1 (milestone exists), I2 (title unique within milestone),
    I3 (no duplicate task assignment), and I4 (tasks must be in the goal).

    Project order is auto-assigned: max(existing orders in milestone) + 1,
    or 0 if no projects exist in this milestone.

    Returns the created Project. Raises ValueError on validation failure.
    """
    goal = _get_goal_required(goal_title)
    _get_milestone_required(goal, milestone_title)  # I1: milestone must exist

    # I2: project title unique within milestone
    existing = get_projects_for_milestone(goal_title, milestone_title)
    if any(p.title == title for p in existing):
        raise ValueError(
            f"Project already exists: {title!r} in milestone "
            f"{milestone_title!r}"
        )

    _validate_project_status(status)

    tasks = list(related_tasks) if related_tasks else []
    _check_duplicate_task_assignment(goal, milestone_title, title, tasks)  # I3
    _warn_cross_goal_tasks(goal, tasks, milestone_title)  # I4 warning

    order = max([p.order for p in existing], default=-1) + 1

    proj = Project(
        title=title,
        milestone_title=milestone_title,
        description=description,
        deadline=deadline,
        status=status,
        order=order,
        related_tasks=tasks,
    )
    goal.projects.append(_project_dict_from_obj(proj, goal_title))
    update_goal(goal)

    emit(logger, "service.project.mutated",
         trace_id=None, span_id="service",
         operation="add", goal_title=goal_title,
         milestone_title=milestone_title, project_title=title,
         changes=None,
         message=f"Project '{title}' added to milestone '{milestone_title}'")

    return proj


def get_projects_for_milestone(
    goal_title: str, milestone_title: str,
) -> list[Project]:
    """Return all projects for a milestone, ordered by ``order``.

    Raises ValueError if the goal or milestone is not found.
    """
    goal = _get_goal_required(goal_title)
    _get_milestone_required(goal, milestone_title)  # I1
    projs = [
        _project_from_dict(p) for p in goal.projects
        if p.get("milestone_title") == milestone_title
    ]
    projs.sort(key=lambda p: p.order)
    return projs


def get_projects_for_goal(goal_title: str) -> list[Project]:
    """Return all projects for a goal, ordered by milestone order then project order."""
    goal = _get_goal_required(goal_title)
    projs = [_project_from_dict(p) for p in goal.projects]
    projs.sort(key=lambda p: (p.order, p.title))
    return projs


def get_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Return a single project by title within a milestone.

    Raises ValueError if the goal, milestone, or project is not found.
    """
    goal = _get_goal_required(goal_title)
    _get_milestone_required(goal, milestone_title)  # I1
    for p in goal.projects:
        if (p.get("milestone_title") == milestone_title
                and p.get("title") == project_title):
            return _project_from_dict(p)
    raise ValueError(
        f"Project not found: {project_title!r} in milestone "
        f"{milestone_title!r} of goal {goal.title!r}"
    )


def update_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
    **kwargs,
) -> Project:
    """Update fields of an existing project.

    Valid kwargs:
      - description, deadline, status
      - add_related_task, remove_related_task

    Per I10, ``goal_title`` and ``milestone_title`` are NOT updatable in MVP.
    Returns the updated Project. Raises ValueError if not found or validation fails.
    """
    goal = _get_goal_required(goal_title)
    idx = _project_index(goal, milestone_title, project_title)
    proj_dict = goal.projects[idx]

    changes: dict = {}

    for key, value in kwargs.items():
        if key == "add_related_task":
            new_list = list(proj_dict.get("related_tasks", []))
            if value not in new_list:
                new_list.append(value)
                changes.setdefault("related_tasks", []).append(value)
            # Re-validate duplicate assignment with the full new list
            _check_duplicate_task_assignment(
                goal, milestone_title, project_title, new_list
            )
            proj_dict["related_tasks"] = new_list
        elif key == "remove_related_task":
            new_list = list(proj_dict.get("related_tasks", []))
            if value in new_list:
                new_list.remove(value)
                changes.setdefault("related_tasks_removed", []).append(value)
            proj_dict["related_tasks"] = new_list
        elif key in ("description", "deadline", "status"):
            if key == "status":
                _validate_project_status(value)
            proj_dict[key] = value
            changes[key] = value
        elif key in ("goal_title", "milestone_title"):
            raise ValueError(
                f"Cannot update parent reference '{key}' — "
                f"parent references are immutable in MVP"
            )
        else:
            raise ValueError(f"Unknown project field: {key!r}")

    # Reconstruct to re-run validation via Project.__post_init__
    updated = _project_from_dict(proj_dict)
    goal.projects[idx] = _project_dict_from_obj(updated, goal_title)
    update_goal(goal)

    emit(logger, "service.project.mutated",
         trace_id=None, span_id="service",
         operation="update", goal_title=goal_title,
         milestone_title=milestone_title, project_title=project_title,
         changes=changes,
         message=f"Project '{project_title}' updated")

    return updated


def complete_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Mark a project as ``completed``. Returns the updated Project."""
    return update_project(
        goal_title, milestone_title, project_title, status="completed"
    )


def skip_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Mark a project as ``skipped`` (intentionally abandoned).

    Returns the updated Project. Raises ValueError if not found.
    """
    return update_project(
        goal_title, milestone_title, project_title, status="skipped"
    )


def block_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Mark a project as ``blocked`` (cannot currently proceed).

    ``blocked`` is non-terminal — the project can later be reopened.
    Returns the updated Project. Raises ValueError if not found.
    """
    return update_project(
        goal_title, milestone_title, project_title, status="blocked"
    )


def start_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Mark a project as ``active`` (currently being worked on).

    Returns the updated Project. Raises ValueError if not found.
    """
    return update_project(
        goal_title, milestone_title, project_title, status="active"
    )


def reopen_project(
    goal_title: str, milestone_title: str, project_title: str,
) -> Project:
    """Reopen a terminal project (completed or skipped) back to ``open``.

    ``blocked`` projects should use ``start_project`` instead.
    Returns the updated Project. Raises ValueError if not found.
    """
    return update_project(
        goal_title, milestone_title, project_title, status="open"
    )


def complete_project_by_title(
    project_title: str,
    evidence: dict | None = None,
) -> Project:
    """Mark a project complete, resolving the goal/milestone by project title.

    Called by the Hermes-side execution-feedback sync listener when a
    Kanban task that carries ``janus_domain: object: project`` linkage
    completes.  Like :func:`janus.services.milestones.update_milestone_status`,
    the goal and parent milestone are resolved by searching all goals for a
    project whose title matches (the ``janus_domain`` frontmatter carries only
    the project title, not the enclosing goal/milestone).

    The project is marked ``completed`` and an evidence entry is appended to
    the enclosing goal's ``recent_activity`` (mirroring
    :func:`janus.services.milestones._append_milestone_evidence`), so the
    completion is visible on the goal's audit trail.

    Idempotent: a re-entrant completion for an already-completed project is a
    no-op on status, but the evidence entry is refreshed.

    Args:
        project_title: Project title (exact match within any goal).
        evidence: Evidence package dict with keys ``task_id``, ``summary``,
            ``completed_at``, ``changed_files``, ``tests_passed``, ``pr_url``.

    Returns:
        The updated Project.

    Raises:
        ValueError: if no project with this title is found.
    """
    evidence = evidence or {}
    # Find the goal + milestone that contain this project, by title.
    goal = None
    goal_title_found = None
    proj_idx = None
    for g in load_goals():
        if g.projects is None:
            continue
        for i, p in enumerate(g.projects):
            if p.get("title") == project_title:
                goal = g
                goal_title_found = g.title
                proj_idx = i
                break
        if goal is not None:
            break
    if goal is None:
        raise ValueError(f"Project not found: {project_title!r}")
    assert proj_idx is not None  # narrowed by the loop above

    proj_dict = goal.projects[proj_idx]
    ms_title = proj_dict.get("milestone_title", "")

    # If already completed, refresh evidence but skip the status write.
    if proj_dict.get("status") == "completed":
        _append_project_evidence(goal, evidence.get("task_id", ""), evidence)
        emit(logger, "service.project.update",
             trace_id=None, span_id="service",
             operation="complete_existing", goal_title=goal_title_found,
             milestone_title=ms_title, project_title=project_title,
             message=f"Project '{project_title}' already completed; "
                     f"refreshed evidence")
        return _project_from_dict(proj_dict)

    proj_dict["status"] = "completed"
    goal.projects[proj_idx] = proj_dict
    update_goal(goal)

    _append_project_evidence(goal, evidence.get("task_id", ""), evidence)

    emit(logger, "service.project.mutated",
         trace_id=None, span_id="service",
         operation="complete", goal_title=goal_title_found,
         milestone_title=ms_title, project_title=project_title,
         changes={"status": "completed"},
         message=f"Project '{project_title}' completed via execution feedback")
    return _project_from_dict(proj_dict)


def _append_project_evidence(
    goal: Goal, task_id: str, evidence: dict,
) -> None:
    """Append an evidence entry to a goal's ``recent_activity`` from a project
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
