"""Next-action derivation for Janus goal execution planning.

Replaces the "first open task" logic with a rules-based engine that
considers task ordering, milestone state, and goal structure.

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


def _milestone_objs(goal: Goal) -> list[Milestone]:
    """Construct ordered Milestone objects from goal.milestones dicts."""
    mss = [Milestone(**dict(m)) for m in goal.milestones]
    mss.sort(key=lambda m: m.order)
    return mss


def _open_task_titles(tasks: list[Task]) -> set[str]:
    """Set of currently-open task titles."""
    return {t.title for t in tasks}


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
    # completed/skipped.
    current_ms = _first_active_milestone(milestone_objs)
    if current_ms is not None:
        for rt in current_ms.related_tasks or []:
            if rt in open_titles:
                # Task is open AND belongs to the current milestone
                return NextAction(
                    title=rt,
                    kind="task",
                    reason=f"Next task in milestone '{current_ms.title}'",
                    goal_title=goal.title,
                )

    # --- R2: Open task outside any milestone ---
    # Collect task titles that are NOT in any active milestone.
    # Per spec: "A task is 'in a milestone' if its title appears in that
    # milestone's related_tasks." We check against ALL milestones to
    # determine membership, then fall back to goal.related_tasks order.
    if goal.related_tasks:
        milestone_task_titles = set()
        for m in milestone_objs:
            milestone_task_titles.update(m.related_tasks or [])

        for rt in goal.related_tasks:
            if rt in open_titles and rt not in milestone_task_titles:
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


def _first_active_milestone(milestones: list[Milestone]) -> Milestone | None:
    """Return the first milestone whose status is not 'completed' or 'skipped'.

    Returns None if all milestones are completed or skipped (or list is empty).
    """
    for m in milestones:
        if m.status in ("open", "in_progress"):
            return m
    return None
