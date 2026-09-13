"""Next-action derivation for Janus goal execution planning.

Replaces the "first open task" logic with a rules-based engine that
considers task ordering, milestone state, and goal structure.

Task-to-milestone membership is derived dynamically (not stored) per
ADR-003 Q3: a shared task "belongs to" whichever non-terminal milestone
is earliest in ``order``. As earlier milestones complete or are skipped,
the task becomes eligible for the next non-terminal milestone that
contains it.

When a Goal has Projects (see design spec:
docs/design/goal_milestone_project_task_hierarchy.md), the engine traverses
the full hierarchy:

    Goal -> Current Milestone -> Current Project -> Open Task

Project assignment always overrides dynamic milestone derivation (I6).
Goals without Projects retain the legacy R1-R5 behavior unchanged.

See docs/design/execution_planning.md for the full rule table.
"""

from dataclasses import dataclass
from datetime import date

from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.task import Task


@dataclass
class NextAction:
    """The derived next action for a goal.

    ``kind`` is "task", "milestone", or "project".
    ``score`` is 0 by default — the attention engine assigns scores based
    on urgency; next actions are not self-scoring.
    """

    title: str
    kind: str          # "task" | "milestone" | "project"
    reason: str
    goal_title: str
    score: int = 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _milestone_objs(goal: Goal) -> list[Milestone]:
    """Construct ordered Milestone objects from goal.milestones dicts.

    Filters out any legacy ``related_tasks`` key for backward compatibility
    with old data files (task membership is now derived dynamically).
    """
    mss = []
    for d in goal.milestones:
        filtered = {k: v for k, v in dict(d).items() if k != "related_tasks"}
        mss.append(Milestone(**filtered))
    mss.sort(key=lambda m: m.order)
    return mss


def _project_objs(goal: Goal) -> list[Project]:
    """Construct Project objects from goal.projects dicts, ordered."""
    projs = []
    for d in goal.projects:
        projs.append(Project(
            title=d["title"],
            milestone_title=d.get("milestone_title", ""),
            description=d.get("description", ""),
            deadline=d.get("deadline"),
            status=d.get("status", "open"),
            order=d.get("order", 0),
            related_tasks=list(d.get("related_tasks", [])),
        ))
    projs.sort(key=lambda p: (p.order, p.title))
    return projs


def _open_task_titles(tasks: list[Task]) -> set[str]:
    """Set of currently-open task titles."""
    return {t.title for t in tasks}


def _first_active_milestone(milestones: list[Milestone]) -> Milestone | None:
    """Return the first milestone whose status is not 'completed' or 'skipped'.

    Returns None if all milestones are completed or skipped (or list is empty).
    """
    for m in milestones:
        if m.status in ("open", "in_progress"):
            return m
    return None


def _first_non_terminal_milestone(
    milestones: list[Milestone],
) -> Milestone | None:
    """Return the earliest non-terminal milestone by order.

    A non-terminal milestone has status ``open`` or ``in_progress``.
    This is the dynamic assignment target for shared tasks — a task
    that is shared across milestones belongs to this milestone at
    derivation time. As this milestone completes or is skipped, the
    task moves to the next non-terminal milestone.
    """
    return _first_active_milestone(milestones)


# ── Dynamic derivation ──────────────────────────────────────────────────────

def derive_milestone_tasks(
    milestone: Milestone,
    all_milestones: list[Milestone],
    goal: Goal,
    open_task_titles: set[str],
) -> list[str]:
    """Dynamically derive which open tasks belong to *milestone*.

    Per ADR-003 Q3: a shared task "belongs to" whichever non-terminal
    milestone contains it first in ``order``. Since task-to-milestone
    membership is NOT stored on the milestone, we derive it:

    * The goal's ``related_tasks`` is the canonical list of tasks that
      support the goal as a whole.
    * A task is "in a milestone" if this milestone is the **earliest
      non-terminal** milestone among *all* milestones.
    * All open tasks from ``goal.related_tasks`` that belong to the
      earliest non-terminal milestone are returned.

    If *milestone* is the earliest non-terminal milestone, ALL open goal
    tasks are assigned to it (they are shared). If *milestone* is not the
    earliest non-terminal milestone, no tasks are assigned to it (they
    belong to the current active milestone instead).

    Args:
        milestone: The milestone to derive tasks for.
        all_milestones: All milestones for the goal, sorted by order.
        goal: The parent Goal (provides ``related_tasks``).
        open_task_titles: Set of currently-open task titles.

    Returns:
        List of open task titles (in goal.related_tasks order) that
        belong to *milestone* based on current state.
    """
    active_ms = _first_non_terminal_milestone(all_milestones)

    # If this milestone is not the current active (earliest non-terminal)
    # one, then shared tasks belong to the active milestone, not this one.
    if active_ms is None or active_ms.order != milestone.order:
        return []

    # All open tasks from goal.related_tasks belong to the current active
    # milestone. Tasks are shared — they belong to whichever non-terminal
    # milestone is earliest in order.
    return [rt for rt in goal.related_tasks if rt in open_task_titles]


def derive_milestone_task_set(
    milestones: list[Milestone],
    goal: Goal,
    open_task_titles: set[str],
) -> set[str]:
    """Return the set of task titles belonging to the current active milestone.

    This is the dynamic equivalent of the old ``milestone.related_tasks``.
    Returns the open tasks from ``goal.related_tasks`` that belong to the
    earliest non-terminal milestone.

    If there are no non-terminal milestones, returns an empty set (no tasks
    belong to any milestone — they are all "outside any milestone" per R2).
    """
    active_ms = _first_non_terminal_milestone(milestones)
    if active_ms is None:
        return set()
    return set(derive_milestone_tasks(active_ms, milestones, goal, open_task_titles))


# ── Project-aware helpers ────────────────────────────────────────────────────

def _get_project_by_title(
    projects: list[Project], milestone_title: str, project_title: str,
) -> Project | None:
    """Find a Project by milestone + title within a goal's project list."""
    for p in projects:
        if (p.milestone_title == milestone_title
                and p.title == project_title):
            return p
    return None


def _assigned_project_tasks(projects: list[Project]) -> set[str]:
    """Return the set of task titles that are explicitly assigned to any Project.

    Per I3/I6: tasks assigned to a Project override the dynamic derivation.
    """
    return {
        t
        for p in projects
        for t in p.related_tasks
    }


def _find_project_for_milestone(
    projects: list[Project], milestone_title: str,
) -> Project | None:
    """Return the first non-terminal Project for a given milestone, by order.

    Excludes ``completed`` and ``skipped`` Projects. ``blocked`` projects
    are not actionable as task containers but are still returned for
    visibility — the caller decides whether to surface a task or the
    project itself.
    """
    for p in sorted(projects, key=lambda p: p.order):
        if p.milestone_title != milestone_title:
            continue
        if p.status in ("completed", "skipped"):
            continue
        return p
    return None


# ── Next-action engine ──────────────────────────────────────────────────────

def derive_next_action(
    goal: Goal,
    tasks: list[Task],
    completed_task_titles: set[str],
    today: date,
    projects: list[Project] | None = None,
) -> NextAction | None:
    """Derive the next action for a goal.

    When ``projects`` is None or empty, the existing R1-R5 legacy behavior
    remains unchanged (backward compatibility, D9).

    When Projects exist for the goal, the engine performs hierarchical
    traversal (D8):

        Goal -> Current Milestone -> Current Project -> Open Task

    Project assignment always overrides dynamic milestone derivation (I6, D4).

    Project-aware priority ordering (spec §10):
      P1 — Current Project has an open Task        -> Task
      P2 — Current Milestone has unassigned open  -> Task (legacy derivation)
      P3 — Current Project has no open Tasks      -> Project
      P4 — Next Milestone has an eligible Project -> Project
      P5 — Next Milestone has unassigned open Task -> Task
      P6 — Next Milestone exists, no actionable   -> Milestone
      P7 — Nothing actionable                     -> None

    Args:
        goal: Goal with milestones loaded (list of dicts).
        tasks: Open (not completed) tasks.
        completed_task_titles: Set of completed task titles.
        today: Current date (reserved for future deadline-aware sorting).
        projects: Optional explicit list of Project objects. When None or
            empty, legacy R1-R5 logic is used.
    """
    del today  # reserved for future deadline-aware sorting

    open_titles = _open_task_titles(tasks)
    milestone_objs = _milestone_objs(goal)

    # When no Projects are provided, use legacy dynamic derivation.
    # This preserves backward compatibility (D9): goals without Projects
    # behave exactly as before.
    if not projects:
        # --- R1: Open task in the current/next milestone ---
        current_ms = _first_active_milestone(milestone_objs)
        if current_ms is not None:
            current_ms_tasks = derive_milestone_task_set(
                milestone_objs, goal, open_titles
            )
            for rt in goal.related_tasks:
                if rt in open_titles and rt in current_ms_tasks:
                    return NextAction(
                        title=rt,
                        kind="task",
                        reason=f"Next task in milestone '{current_ms.title}'",
                        goal_title=goal.title,
                    )

        # --- R2: Open task outside any milestone ---
        if goal.related_tasks:
            current_ms_task_set = derive_milestone_task_set(
                milestone_objs, goal, open_titles
            )
            for rt in goal.related_tasks:
                if rt in open_titles and rt not in current_ms_task_set:
                    return NextAction(
                        title=rt,
                        kind="task",
                        reason="No milestone assigned",
                        goal_title=goal.title,
                    )

        # --- R3: Next open or in_progress milestone (no open tasks found) ---
        if current_ms is not None:
            return NextAction(
                title=current_ms.title,
                kind="milestone",
                reason="Milestone not yet reached",
                goal_title=goal.title,
            )

        # --- R4: First uncompleted milestone in sequence ---
        if milestone_objs:
            for m in milestone_objs:
                if m.status in ("open", "in_progress"):
                    return NextAction(
                        title=m.title,
                        kind="milestone",
                        reason="Next milestone in sequence",
                        goal_title=goal.title,
                    )

        # --- R5: No next action ---
        return None

    # ─── Project-aware hierarchical traversal ───

    # Determine current (earliest non-terminal) milestone.
    current_ms = _first_active_milestone(milestone_objs)

    # P1: Current Project has an open Task
    if current_ms is not None:
        current_proj = _find_project_for_milestone(projects, current_ms.title)
        if current_proj is not None:
            for t in current_proj.related_tasks:
                if t in open_titles:
                    return NextAction(
                        title=t,
                        kind="task",
                        reason=(
                            f"Open task in project '{current_proj.title}' "
                            f"within milestone '{current_ms.title}'"
                        ),
                        goal_title=goal.title,
                    )
            # P3: Current Project has no open Tasks
            return NextAction(
                title=current_proj.title,
                kind="project",
                reason=f"Project '{current_proj.title}' has no open tasks",
                goal_title=goal.title,
            )

    # P2: Current Milestone has unassigned open Task (legacy derivation)
    assigned = _assigned_project_tasks(projects)
    if current_ms is not None:
        current_ms_tasks = derive_milestone_task_set(
            milestone_objs, goal, open_titles
        )
        for rt in goal.related_tasks:
            if (rt in open_titles
                    and rt in current_ms_tasks
                    and rt not in assigned):
                return NextAction(
                    title=rt,
                    kind="task",
                    reason=f"Next unassigned task in milestone '{current_ms.title}'",
                    goal_title=goal.title,
                )

    # P4: Next Milestone has an eligible Project
    if current_ms is not None:
        start_idx = None
        for i, m in enumerate(milestone_objs):
            if m.order == current_ms.order:
                start_idx = i + 1
                break
        if start_idx is not None:
            for m in milestone_objs[start_idx:]:
                if m.status in ("completed", "skipped"):
                    continue
                proj = _find_project_for_milestone(projects, m.title)
                if proj is not None:
                    return NextAction(
                        title=proj.title,
                        kind="project",
                        reason=f"Eligible project in milestone '{m.title}'",
                        goal_title=goal.title,
                    )
    else:
        # No current milestone — start from the first non-terminal milestone
        for m in milestone_objs:
            if m.status in ("completed", "skipped"):
                continue
            proj = _find_project_for_milestone(projects, m.title)
            if proj is not None:
                return NextAction(
                    title=proj.title,
                    kind="project",
                    reason=f"Eligible project in milestone '{m.title}'",
                    goal_title=goal.title,
                )

    # P5: Next Milestone has an unassigned open Task
    all_milestone = milestone_objs
    if current_ms is not None:
        # Look at milestones after the current one
        start_idx = None
        for i, m in enumerate(milestone_objs):
            if m.order == current_ms.order:
                start_idx = i + 1
                break
        search_range = milestone_objs[start_idx:] if start_idx else []
    else:
        search_range = milestone_objs
    for m in search_range:
        if m.status in ("completed", "skipped"):
            continue
        ms_tasks = derive_milestone_tasks(m, all_milestone, goal, open_titles)
        for rt in goal.related_tasks:
            if (rt in open_titles
                    and rt in ms_tasks
                    and rt not in assigned):
                return NextAction(
                    title=rt,
                    kind="task",
                    reason=f"Unassigned task in milestone '{m.title}'",
                    goal_title=goal.title,
                )

    # P6: Next Milestone exists but has no actionable Project/Task
    if current_ms is not None:
        start_idx = None
        for i, m in enumerate(milestone_objs):
            if m.order == current_ms.order:
                start_idx = i + 1
                break
        search_range = milestone_objs[start_idx:] if start_idx else []
    else:
        search_range = milestone_objs
    for m in search_range:
        if m.status in ("completed", "skipped"):
            continue
        return NextAction(
            title=m.title,
            kind="milestone",
            reason=f"Next milestone '{m.title}' has no actionable projects or tasks",
            goal_title=goal.title,
        )

    # P7: Nothing actionable remains
    return None
