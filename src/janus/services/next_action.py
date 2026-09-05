"""Next-action derivation for Janus goal execution planning.

Replaces the "first open task" logic with a rules-based engine that
considers task ordering, milestone state, and goal structure.

Task-to-milestone membership is derived dynamically (not stored) per
ADR-003 Q3: a shared task "belongs to" whichever non-terminal milestone
is earliest in ``order``. As earlier milestones complete or are skipped,
the task becomes eligible for the next non-terminal milestone that
contains it.

See DESIGN_EXECUTION_PLANNING.md §4 for the full rule table.
"""

from dataclasses import dataclass
from datetime import date

from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.task import Task


@dataclass
class NextAction:
    """The derived next action for a goal.

    ``kind`` is "task" or "milestone".
    ``score`` is 0 by default — the attention engine assigns scores based
    on urgency; next actions are not self-scoring.
    """

    title: str
    kind: str          # "task" | "milestone"
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


# ── Next-action engine ──────────────────────────────────────────────────────

def derive_next_action(
    goal: Goal,
    tasks: list[Task],
    completed_task_titles: set[str],
    today: date,
) -> NextAction | None:
    """Derive the next action for a goal.

    Rules (evaluated in priority order):
      R1 — Open task in the current/next milestone
      R2 — Open task outside any milestone
      R3 — Next open or in_progress milestone (no open tasks)
      R4 — First uncompleted milestone in sequence (all milestones done/skipped,
           but one has order beyond the last completed — surfaces remaining open milestone)
      R5 — No next action (all milestones completed and no open tasks)

    Args:
        goal: Goal with milestones loaded (list of dicts).
        tasks: Open (not completed) tasks.
        completed_task_titles: Set of completed task titles.
        today: Current date (reserved for future deadline-aware sorting).
    """
    del today  # reserved for future deadline-aware sorting
    open_titles = _open_task_titles(tasks)
    milestone_objs = _milestone_objs(goal)

    # --- R1: Open task in the current/next milestone ---
    # The "current/next milestone" is the first milestone whose status is not
    # completed/skipped. Tasks are assigned dynamically — all open goal tasks
    # belong to the earliest non-terminal milestone.
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
    # Collect task titles that are NOT in the current active milestone's
    # dynamically-derived task set. Tasks in goal.related_tasks that are
    # open but not assigned to the current milestone fall through to R2.
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
    # All milestones are completed/skipped, but there may still be milestones
    # in the list. Per spec: "All milestones are completed/skipped, but one
    # has order beyond the last completed" — surface it.
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
    # No milestones and no open related tasks.
    if not milestone_objs and goal.related_tasks:
        # Goal has related tasks but no milestones — R2 should have caught open ones.
        # If we reach here, all related tasks are completed.
        return None

    return None
